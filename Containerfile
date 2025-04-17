FROM quay.io/centos/centos:stream9

USER root

RUN groupadd -g 65532 tools && \
    useradd -u 65532 -g tools -m tools

# Set working directory
WORKDIR /app
RUN chown -R tools:tools /app


RUN dnf install -y python3.12 python3.12-devel python3.12-pip git && \
    alternatives --install /usr/bin/python python /usr/bin/python3.12 1 && \
    alternatives --install /usr/bin/pip pip /usr/bin/pip3.12 1 && \
    dnf groupinstall -y "Development Tools"


COPY feedback_exporter feedback_exporter
COPY jira_scraper jira_scraper
COPY evaluation evaluation
COPY log_parser log_parser
COPY pdm.lock pyproject.toml Makefile .
RUN chown -R tools:tools /app

# required to prepare to get a model
RUN mkdir -p /home/tools/.cache/huggingface && \
    chown -R tools:tools /home/tools/.cache

USER tools
ENV PATH="/home/tools/.local/bin:$PATH"
ENV PDM_IGNORE_SAVED_PYTHON=1

# no packge for centos - get with curl
RUN curl -sSL https://pdm.fming.dev/install-pdm.py | python && \
    pdm config python.use_venv false

RUN pdm use -f /usr/bin/python3.12 && \
    pdm install
