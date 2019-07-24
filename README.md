[TOC]

# Basics

Basic pattern of usage metrics lib:

1. Instantiate root Metr. [see](#markdown-header-instantiating-metr) 
2. Instantiate needed handlers. [see](#markdown-header-handlers)
3. Add handlers to root Metr.
4. Get root Metr child wherever you want. [see](#markdown-header-metrs-inheritance) and [also](#markdown-header-metrs-storage)
5. Create records. [see](#markdown-header-recorders)
6. PROFIT!

## Instantiating Metr
```python
import metrics

# from metrics module
root_metr = metrics.get_metr('etl-script-1')
assert root_metr.tag == 'etl-script-1'

# from other Metr
network_metr = root_metr.get_metr('facebook')
assert network_metr.tag == 'etl-script-1.facebook'
```

## Metrs inheritance

As you can see Metr has `tag` attribute. It is string value.
Tag may contain dots, dot separates levels of tag and describes relations
between Metrs.

```python
import metrics

root_metr = metrics.get_metr('etl-script-1')
network_metr = metrics.get_metr('etl-script-1.facebook')
data_metr = metrics.get_metr('etl-script-1.facebook.transformed')
assert network_metr._parent is root_metr
assert data_metr._parent is network_metr
```

When Metr should handle record (Point) first of all it sends point to own registered
handlers, then (if parent metr exists) - sends produced point to parent Metr.

## Handlers

When point produced - it should be handled somehow: store to DB, print in stdout, save to file, etc.
Metrics module contains several implemented Handlers:

### *LoggingHandler*
Purpose: use Python builtin logging to log Points

```python
import metrics
import logging

root_metr = metrics.get_metr('etl-script-1')
logging_handler = metrics.LoggingHandler(logging.INFO, 'ROOT_METR')
root_metr.add_handler(logging_handler)

root_metr.rec(42)
# will produce log message:
# INFO:ROOT_METR:[thread:4379502016][thread_name:MainThread][ray:0fe3905d-61e4-4291-8e11-0dddfb3e1c17][created:2019-07-24 07:49:07.435708][tag:etl-script-1][value:42]
```

### *RDSHandler*

Purpose: insert Points to RedShift database as row
```python
import metrics
import psycopg2

root_metr = metrics.get_metr('etl-script-1')
db_conn = psycopg2.connect(**kwargs) # passing connection parameters
rds_handler = metrics.RDSHandler(db_conn)
root_metr.add_handler(rds_handler)

root_metr.rec(42)

# will execute query
#
# INSERT INTO some_table (timestamp, tag, value, ray_id) VALUES ('2019-07-24 07:49:07.435708','etl-script-1', 42, '0fe3905d-61e4-4291-8e11-0dddfb3e1c17');
```
Table name is an attribute of class `RDSHandler`, if you want to override it:

```python
import metrics
import psycopg2
# make your own RDS Handler
class MyRDSHandler(metrics.RDSHandler):
    table = 'my_table'
    
# or assign new table name to handler class
metrics.RDSHandler.table = 'my_table'

# or assign table name for certain instance of handler
rds_handler = metrics.RDSHandler(psycopg2.connect(**kwargs))
rds_handler.table = 'my_table'

```

## Metrs storage

All created Metrs by metrics.get_metr or <Metr>.get_metr are stored in metrics module global hash map, 
where tag is key to certain Metr instance

```python
import metrics

one_metr = metrics.get_metr('a')
two_metr = metrics.get_metr('a.b')
assert two_metr is one_metr.get_metr('b')
one_metr_v2 = metrics.get_metr('a')
assert one_metr_v2 is one_metr
```

## Recorders

Recorders are instances made to handle metric values for certain Metr.
There are three recorders available:

### IntRecorder
`rec` - (`class: IntRecorder`) just handle int value
```python
import metrics
root_metr = metrics.get_metr('etl-script-1.tick_amount')

root_metr.rec(7)

# Will call root_metr.handle_value(7), so root_metr will create Point with tag: etl-script-1.amount, value: 7

```

### CounterRecorder 
`rec_counter` - (`class: CounterRecorder`) can accumulate values
```python
import metrics
root_metr = metrics.get_metr('etl-script-1.total')


with root_metr.rec_counter() as counter:
    for i in range(0,5):
        counter.add(i)

# Will call root_metr.handle_value(10), so root_metr will create Point with tag: etl-script-1.total, value: 10

```
### ExceptionRecorder
`rec_exception` - (`class: ExceptionRecorder`) produce point in case of catched exception
```python
import metrics
root_metr = metrics.get_metr('etl-script-1.errors')


def assert_odd(num: int):
    assert num % 2 > 0
    

assertion_err_rec = root_metr.rec_exception(AssertionError)
for i in range(0,5):
    try:
        assertion_err_rec(assert_odd)(i)
    except AssertionError:
        continue
        
# Will produce three points with tag: etl-script-1.errors, value: 1
```

## Metric Point

Metric point in library is presented by Record object. 
Record object contains the following attributes:

* *created* (datetime.datetime) - time when record was created
* *tag* (str) - metric name
* *value* (int) - value of metric
* *ray_id* (str) - the uniq uuid4 of session

## Point Representation

As we want to store collected metrics somewhere, we should implement
specific representation for certain metric target.
Library contains the following point representations (Formatters)

### SQL point Representation

`class: SQLRecordFormatter`

format record as str of sql values in order: `created, tag, value, ray_id`

For example:
`"'2019-07-10 08:12:37.414017', 'etl-script-1.error', 1, '6ab7bc67-434b-464d-9143-33d8def72980'"`


# Distribution

## Build

see. [Jenkinsfile](./Jenkinsfile)

## Artifact

Docker image: `metrics:master`
With base image: `python:3.6` and env `PYTHONPATH` contains path to metrics package

# Integration

## Dockerfile

Generic Dockerfile for script with metrics included
```dockerfile
ARG BASE_IMAGE=metrics:master
FROM $BASE_IMAGE
COPY ./ /app
WORKDIR /app
RUN pipenv install --system --deploy
ENTRYPOINT ["python3", "main.py"]
```

# Contribute

## Tests

To run tests:
```sh
python -m unittest discover ./tests
```
