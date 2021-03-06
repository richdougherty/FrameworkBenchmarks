#!/usr/bin/env python

import subprocess
import os
import sys
from benchmark import framework_test
from benchmark.utils import gather_tests
import glob
import json
import traceback
import re
import logging
log = logging.getLogger('run-ci')
import time
import threading

# Needed for various imports
sys.path.append('.')
sys.path.append('toolset/setup/linux')
sys.path.append('toolset/benchmark')

class CIRunnner:
  '''
  Manages running TFB on the Travis Continuous Integration system. 
  Makes a best effort to avoid wasting time and resources by running 
  useless jobs. 
  
  Only verifies the first test in each directory 
  '''
  
  def __init__(self, mode, testdir=None):
    '''
    mode = [cisetup|prereq|install|verify] for what we want to do
    testdir  = framework directory we are running
    '''

    self.directory = testdir
    self.mode = mode
    if mode == "cisetup":
      logging.basicConfig(level=logging.DEBUG)
    else:
      logging.basicConfig(level=logging.INFO)

    try:
      # NOTE: THIS IS VERY TRICKY TO GET RIGHT!
      #
      # Our goal: Look at the files changed and determine if we need to 
      # run a verification for this folder. For a pull request, we want to 
      # see the list of files changed by any commit in that PR. For a 
      # push to master, we want to see a list of files changed by the pushed
      # commits. If this list of files contains the current directory, or 
      # contains the toolset/ directory, then we need to run a verification
      # 
      # If modifying, please consider: 
      #  - the commit range for a pull request is the first PR commit to 
      #    the github auto-merge commit
      #  - the commits in the commit range may include merge commits
      #    other than the auto-merge commit. An git log with -m 
      #    will know that *all* the files in the merge were changed, 
      #    but that is not the changeset that we care about
      #  - git diff shows differences, but we care about git log, which
      #    shows information on what was changed during commits
      #  - master can (and will!) move during a build. This is one 
      #    of the biggest problems with using git diff - master will 
      #    be updated, and those updates will include changes to toolset, 
      #    and suddenly every job in the build will start to run instead 
      #    of fast-failing
      #  - commit_range is not set if there was only one commit pushed, 
      #    so be sure to test for that on both master and PR
      #  - commit_range and commit are set very differently for pushes
      #    to an owned branch versus pushes to a pull request, test
      #  - For merge commits, the TRAVIS_COMMIT and TRAVIS_COMMIT_RANGE 
      #    will become invalid if additional commits are pushed while a job is 
      #    building. See https://github.com/travis-ci/travis-ci/issues/2666
      #  - If you're really insane, consider that the last commit in a 
      #    pull request could have been a merge commit. This means that 
      #    the github auto-merge commit could have more than two parents
      #  
      #  - TEST ALL THESE OPTIONS: 
      #      - On a branch you own (e.g. your fork's master)
      #          - single commit
      #          - multiple commits pushed at once
      #          - commit+push, then commit+push again before the first
      #            build has finished. Verify all jobs in the first build 
      #            used the correct commit range
      #          - multiple commits, including a merge commit. Verify that
      #            the unrelated merge commit changes are not counted as 
      #            changes the user made
      #      - On a pull request
      #          - repeat all above variations
      #
      #
      # ==== CURRENT SOLUTION FOR PRs ====
      #
      # For pull requests, we will examine Github's automerge commit to see
      # what files would be touched if we merged this into the current master. 
      # You can't trust the travis variables here, as the automerge commit can
      # be different for jobs on the same build. See https://github.com/travis-ci/travis-ci/issues/2666
      # We instead use the FETCH_HEAD, which will always point to the SHA of 
      # the lastest merge commit. However, if we only used FETCH_HEAD than any
      # new commits to a pull request would instantly start affecting currently
      # running jobs and the the list of changed files may become incorrect for
      # those affected jobs. The solution is to walk backward from the FETCH_HEAD
      # to the last commit in the pull request. Based on how github currently 
      # does the automerge, this is the second parent of FETCH_HEAD, and 
      # therefore we use FETCH_HEAD^2 below
      #
      # This may not work perfectly in situations where the user had advanced 
      # merging happening in their PR. We correctly handle them merging in 
      # from upstream, but if they do wild stuff then this will likely break
      # on that. However, it will also likely break by seeing a change in 
      # toolset and triggering a full run when a partial run would be 
      # acceptable
      #
      # ==== CURRENT SOLUTION FOR OWNED BRANCHES (e.g. master) ====
      #
      # This one is fairly simple. Find the commit or commit range, and 
      # examine the log of files changes. If you encounter any merges, 
      # then fully explode the two parent commits that made the merge
      # and look for the files changed there. This is an aggressive 
      # strategy to ensure that commits to master are always tested 
      # well
      log.debug("TRAVIS_COMMIT_RANGE: %s", os.environ['TRAVIS_COMMIT_RANGE'])
      log.debug("TRAVIS_COMMIT      : %s", os.environ['TRAVIS_COMMIT'])

      is_PR = (os.environ['TRAVIS_PULL_REQUEST'] != "false")
      if is_PR:
        log.debug('I am testing a pull request')
        first_commit = os.environ['TRAVIS_COMMIT_RANGE'].split('...')[0]
        last_commit = subprocess.check_output("git rev-list -n 1 FETCH_HEAD^2", shell=True).rstrip('\n')
        log.debug("Guessing that first commit in PR is : %s", first_commit)
        log.debug("Guessing that final commit in PR is : %s", last_commit)

        if first_commit == "":
          # Travis-CI is not yet passing a commit range for pull requests
          # so we must use the automerge's changed file list. This has the 
          # negative effect that new pushes to the PR will immediately 
          # start affecting any new jobs, regardless of the build they are on
          log.debug("No first commit, using Github's automerge commit")
          self.commit_range = "--first-parent -1 -m FETCH_HEAD"
        elif first_commit == last_commit:
          # There is only one commit in the pull request so far, 
          # or Travis-CI is not yet passing the commit range properly 
          # for pull requests. We examine just the one commit using -1
          #
          # On the oddball chance that it's a merge commit, we pray  
          # it's a merge from upstream and also pass --first-parent 
          log.debug("Only one commit in range, examining %s", last_commit)
          self.commit_range = "-m --first-parent -1 %s" % last_commit
        else: 
          # In case they merged in upstream, we only care about the first 
          # parent. For crazier merges, we hope
          self.commit_range = "--first-parent %s...%s" % (first_commit, last_commit)

      if not is_PR:
        log.debug('I am not testing a pull request')
        # If more than one commit was pushed, examine everything including 
        # all details on all merges
        self.commit_range = "-m %s" % os.environ['TRAVIS_COMMIT_RANGE']
        
        # If only one commit was pushed, examine that one. If it was a 
        # merge be sure to show all details
        if self.commit_range == "":
          self.commit_range = "-m -1 %s" % os.environ['TRAVIS_COMMIT']

    except KeyError:
      log.warning("I should only be used for automated integration tests e.g. Travis-CI")
      log.warning("Were you looking for run-tests.py?")
      self.commit_range = "-m HEAD^...HEAD"

    #
    # Find the one test from benchmark_config that we are going to run
    #

    tests = gather_tests()
    dirtests = [t for t in tests if t.directory == testdir]
    
    # Travis-CI is linux only
    osvalidtests = [t for t in dirtests if t.os.lower() == "linux"
                  and (t.database_os.lower() == "linux" or t.database_os.lower() == "none")]
    
    # Travis-CI only has some supported databases
    validtests = [t for t in osvalidtests if t.database.lower() == "mysql"
                  or t.database.lower() == "postgres"
                  or t.database.lower() == "mongodb"
                  or t.database.lower() == "none"]
    log.info("Found %s tests (%s for linux, %s for linux and mysql) in directory '%s'", 
      len(dirtests), len(osvalidtests), len(validtests), testdir)
    if len(validtests) == 0:
      log.critical("Found no test that is possible to run in Travis-CI! Aborting!")
      if len(osvalidtests) != 0:
        log.critical("Note: Found these tests that could run in Travis-CI if more databases were supported")
        log.critical("Note: %s", osvalidtests)
        databases_needed = [t.database for t in osvalidtests]
        databases_needed = list(set(databases_needed))
        log.critical("Note: Here are the needed databases:")
        log.critical("Note: %s", databases_needed)
      sys.exit(1)

    self.names = [t.name for t in validtests]
    log.info("Choosing to use test %s to verify directory %s", self.names, testdir)

  def _should_run(self):
    ''' 
    Decides if the current framework test should be tested. 
    Examines git commits included in the latest push to see if any files relevant to 
    this framework were changed. 
    If you do rewrite history (e.g. rebase) then it's up to you to ensure that both 
    old and new (e.g. old...new) are available in the public repository. For simple
    rebase onto the public master this is not a problem, only more complex rebases 
    may have issues
    '''
    # Don't use git diff multiple times, it's mega slow sometimes\
    # Put flag on filesystem so that future calls to run-ci see it too
    if os.path.isfile('.run-ci.should_run'):
      return True
    if os.path.isfile('.run-ci.should_not_run'):
      return False

    def touch(fname):
      open(fname, 'a').close()

    log.debug("Using commit range `%s`", self.commit_range)
    log.debug("Running `git log --name-only --pretty=\"format:\" %s`" % self.commit_range)
    changes = subprocess.check_output("git log --name-only --pretty=\"format:\" %s" % self.commit_range, shell=True)
    changes = os.linesep.join([s for s in changes.splitlines() if s]) # drop empty lines
    log.debug("Result:\n%s", changes)

    # Look for changes to core TFB framework code
    if re.search(r'^toolset/', changes, re.M) is not None: 
      log.info("Found changes to core framework code")
      touch('.run-ci.should_run')
      return True
  
    # Look for changes relevant to this test
    if re.search("^%s/" % self.directory, changes, re.M) is None:
      log.info("No changes found for directory %s", self.directory)
      touch('.run-ci.should_not_run')
      return False

    log.info("Changes found for directory %s", self.directory)
    touch('.run-ci.should_run')
    return True

  def run(self):
    ''' Do the requested command using TFB  '''

    if not self._should_run():
      log.info("I found no changes to `%s` or `toolset/`, aborting verification", self.directory)
      return 0

    if self.mode == 'cisetup':
      self.run_travis_setup()
      return 0

    names = ' '.join(self.names)
    command = 'toolset/run-tests.py '
    if self.mode == 'prereq':
      command = command + "--install server --install-only --test ''"
    elif self.mode == 'install':
      command = command + "--install server --install-only --test %s" % names
    elif self.mode == 'verify':
      command = command + "--mode verify --test %s" % names
    else:
      log.critical('Unknown mode passed')
      return 1
    
    # Run the command
    log.info("Running mode %s with commmand %s", self.mode, command)
    try:
      p = subprocess.Popen(command, shell=True)
      p.wait()
      return p.returncode  
    except subprocess.CalledProcessError:
      log.critical("Subprocess Error")
      print traceback.format_exc()
      return 1
    except Exception as err:
      log.critical("Exception from running+wait on subprocess")
      log.error(err.child_traceback)
      return 1

  def run_travis_setup(self):
    log.info("Setting up Travis-CI")
    
    script = '''
    # Needed to download latest MongoDB (use two different approaches)
    sudo apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv 7F0CEB10 || gpg --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys 7F0CEB10
    echo 'deb http://downloads-distro.mongodb.org/repo/ubuntu-upstart dist 10gen' | sudo tee /etc/apt/sources.list.d/mongodb.list

    sudo apt-get update
    
    # MongoDB takes a good 30-45 seconds to turn on, so install it first
    sudo apt-get install mongodb-org

    sudo apt-get install openssh-server

    # Run as travis user (who already has passwordless sudo)
    ssh-keygen -f /home/travis/.ssh/id_rsa -N '' -t rsa
    cat /home/travis/.ssh/id_rsa.pub > /home/travis/.ssh/authorized_keys
    chmod 600 /home/travis/.ssh/authorized_keys

    # =============Setup Databases===========================
    # NOTE: Do not run `--install database` in travis-ci! 
    #       It changes DB configuration files and will break everything
    # =======================================================

    # Add data to mysql
    mysql -uroot < config/create.sql

    # Setup Postgres
    psql --version
    sudo useradd benchmarkdbuser -p benchmarkdbpass
    sudo -u postgres psql template1 < config/create-postgres-database.sql
    sudo -u benchmarkdbuser psql hello_world < config/create-postgres.sql

    # Setup MongoDB (see install above)
    mongod --version
    until nc -z localhost 27017 ; do echo Waiting for MongoDB; sleep 1; done
    mongo < config/create.js
    '''

    def sh(command):
      log.info("Running `%s`", command)
      subprocess.check_call(command, shell=True)  

    for command in script.split('\n'):
      command = command.lstrip()
      if command != "" and command[0] != '#':
        sh(command.lstrip())

if __name__ == "__main__":
  args = sys.argv[1:]

  usage = '''Usage: toolset/run-ci.py [cisetup|prereq|install|verify] <framework-directory>
    
    run-ci.py selects one test from <framework-directory>/benchark_config, and 
    automates a number of calls into run-tests.py specific to the selected test. 

    It is guaranteed to always select the same test from the benchark_config, so 
    multiple runs with the same <framework-directory> reference the same test. 
    The name of the selected test will be printed to standard output. 

    cisetup - configure the Travis-CI environment for our test suite
    prereq  - trigger standard prerequisite installation
    install - trigger server installation for the selected test_directory
    verify  - run a verification on the selected test using `--mode verify`

    run-ci.py expects to be run inside the Travis-CI build environment, and 
    will expect environment variables such as $TRAVIS_BUILD'''

  if len(args) != 2:
    print usage
    sys.exit(1)

  mode = args[0]
  testdir = args[1]
  if len(args) == 2 and (mode == "install" 
    or mode == "verify"
    or mode == 'prereq'
    or mode == 'cisetup'):
    runner = CIRunnner(mode, testdir)
  else:
    print usage
    sys.exit(1)
    
  retcode = 0
  try:
    retcode = runner.run()
  except KeyError as ke: 
    log.warning("Environment key missing, are you running inside Travis-CI?")
    print traceback.format_exc()
    retcode = 1
  except:
    log.critical("Unknown error")
    print traceback.format_exc()
    retcode = 1
  finally:  # Ensure that logs are printed
    
    # Only print logs if we ran a verify
    if mode != 'verify':
      sys.exit(retcode)

    # Only print logs if we actually did something
    if os.path.isfile('.run-ci.should_not_run'):
      sys.exit(retcode)

    log.error("Running inside Travis-CI, so I will print err and out to console...")
    
    for name in runner.names:
      log.error("Test %s", name)
      try:
        log.error("Here is ERR:")
        with open("results/ec2/latest/logs/%s/err.txt" % name, 'r') as err:
          for line in err:
            log.info(line.rstrip('\n'))
      except IOError:
        log.error("No ERR file found")

      try:
        log.error("Here is OUT:")
        with open("results/ec2/latest/logs/%s/out.txt" % name, 'r') as out:
          for line in out:
            log.info(line.rstrip('\n'))
      except IOError:
        log.error("No OUT file found")

    sys.exit(retcode)


# vim: set sw=2 ts=2 expandtab