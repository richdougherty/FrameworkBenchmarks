
import subprocess
import sys
import os
import setup_util
from os.path import expanduser

def start(args, logfile, errfile):
  fwroot = args.fwroot
  setup_util.replace_text("cakephp/app/Config/database.php", "'host' => '.*',", "'host' => '" + args.database_host + "',")
  setup_util.replace_text("cakephp/deploy/cake", "\".*\/FrameworkBenchmarks", "\"%s" % fwroot)
  setup_util.replace_text("cakephp/deploy/cake", "Directory .*\/FrameworkBenchmarks", "Directory %s" % fwroot)
  setup_util.replace_text("cakephp/deploy/nginx.conf", "root .*\/FrameworkBenchmarks", "root %s" % fwroot)

  try:
    if os.name == 'nt':
      setup_util.replace_text("cakephp/app/Config/core.php", "'Apc'", "'Wincache'")
      subprocess.check_call('icacls "C:\\FrameworkBenchmarks\\cakephp" /grant "IIS_IUSRS:(OI)(CI)F"', shell=True, stderr=errfile, stdout=logfile)
      subprocess.check_call('appcmd add site /name:PHP /bindings:http/*:8080: /physicalPath:"C:\\FrameworkBenchmarks\\cakephp\\app\\webroot"', shell=True, stderr=errfile, stdout=logfile)
      return 0
    #subprocess.check_call("sudo cp cake/deploy/cake /etc/apache2/sites-available/", shell=True)
    #subprocess.check_call("sudo a2ensite cake", shell=True)
    subprocess.check_call("sudo chown -R www-data:www-data cakephp", shell=True, stderr=errfile, stdout=logfile)
    #subprocess.check_call("sudo /etc/init.d/apache2 start", shell=True)
    subprocess.check_call("sudo php-fpm --fpm-config config/php-fpm.conf -g $TROOT/deploy/php-fpm.pid", shell=True, stderr=errfile, stdout=logfile)
    subprocess.check_call("sudo /usr/local/nginx/sbin/nginx -c $TROOT/deploy/nginx.conf", shell=True, stderr=errfile, stdout=logfile)
    return 0
  except subprocess.CalledProcessError:
    return 1
def stop(logfile, errfile):
  try:
    if os.name == 'nt':
      subprocess.call('appcmd delete site PHP', shell=True, stderr=errfile, stdout=logfile)
      return 0
    subprocess.call("sudo /usr/local/nginx/sbin/nginx -s stop", shell=True, stderr=errfile, stdout=logfile)
    subprocess.call("sudo kill -QUIT $( cat $TROOT/deploy/php-fpm.pid )", shell=True, stderr=errfile, stdout=logfile)
    #subprocess.check_call("sudo a2dissite cake", shell=True)
    #subprocess.check_call("sudo /etc/init.d/apache2 stop", shell=True)
    subprocess.check_call("sudo chown -R $USER:$USER cakephp", shell=True, stderr=errfile, stdout=logfile)
    return 0
  except subprocess.CalledProcessError:
    return 1
