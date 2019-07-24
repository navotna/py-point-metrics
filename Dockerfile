FROM python:3.6
RUN pip3 install pipenv
COPY ./Pipfile* /libs/metrics/

WORKDIR /libs/metrics
RUN pipenv install --system --deploy

COPY metrics /libs/metrics/metrics
COPY tests /libs/metrics/tests

ENV PYTHONPATH="$PYTHONPATH:/libs/metrics"
