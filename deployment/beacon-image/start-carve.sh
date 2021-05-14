#!/bin/bash
docker run -d --restart always --name carve -v "/www:/www" -v "/carve:/carve" anotherhobby/carve
docker run -d --restart always --name nginx -p 80:80 -v "/www:/www" -v "/carve/nginx.conf:/etc/nginx/nginx.conf" nginx:latest
docker run -d --restart always --name beacon -p 8008:8008 -v "/carve:/carve" -w /carve python:slim python carve-beacon-updater.py
