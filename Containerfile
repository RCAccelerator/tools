FROM registry.access.redhat.com/ubi9/python-312

USER root
RUN groupadd -g 65532 tools && \
    useradd -u 65532 -g tools tools

RUN dnf install -y krb5-workstation

WORKDIR /app
RUN chown -R tools:tools /app

COPY feedback_exporter feedback_exporter
COPY data_scraper data_scraper
COPY evaluation evaluation
COPY pdm.lock pyproject.toml Makefile .
RUN make install-pdm install-global

USER tools
