# using python:slim for savings since it's the same container for the updater
FROM python:slim

LABEL maintainer="anotherhobby"

COPY carve-beacon-verification.sh /carve-beacon-verification.sh
RUN chmod a+x /carve-beacon-verification.sh
RUN mkdir /www
RUN apt-get update
RUN apt-get install -y fping

CMD ["/carve-beacon-verification.sh"]