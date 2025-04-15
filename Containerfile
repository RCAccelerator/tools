FROM registry.access.redhat.com/ubi9/python-312

USER root
RUN groupadd -g 65532 tools && \
    useradd -u 65532 -g tools tools

WORKDIR /app
RUN chown -R tools:tools /app

COPY feedback_exporter feedback_exporter
COPY jira_scraper jira_scraper
COPY evaluation evaluation
COPY log_parser log_parser
COPY pdm.lock pyproject.toml Makefile .
RUN make install-pdm install-global

USER tools
