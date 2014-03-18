# --- Created by Ebean DDL
# To stop Ebean DDL generation, remove this comment and start using Evolutions

# --- !Ups

create table world (
  id                        bigint auto_increment not null,
  randomNumber              bigint,
  constraint pk_world primary key (id))
;




# --- !Downs

SET FOREIGN_KEY_CHECKS=0;

drop table world;

SET FOREIGN_KEY_CHECKS=1;

