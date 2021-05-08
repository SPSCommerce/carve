#!/bin/bash
while true; do
  /usr/bin/fping -C 5 -i 1 -q -f /carve/carve.conf &> /www/results-out
  mv -f /www/results-out /www/results
  echo -n `date +%s` > /www/ts-out
  mv -f /www/ts-out /www/ts
  sleep 10
done
