import logging
import time
from argparse import ArgumentParser, Namespace
from typing import Union

import psycopg2

import metrics

__all__ = ["get_millisecs_from_epoch", "extend_arg_parser", "make_rds_handler_from_args"]

logger = logging.getLogger("metrics")


def rds_connection_factory(**kwargs):
    return psycopg2.connect(**kwargs)


def get_millisecs_from_epoch() -> int:
    return int(round(time.time() * 1000))


def extend_arg_parser(parser: ArgumentParser) -> ArgumentParser:
    parser.add_argument("--metrics", action="store_true", help="Send metrics")
    parser.add_argument("-MH", "--metrics-host", help="metrics database host")
    parser.add_argument("-Mp", "--metrics-port", help="metrics database port")
    parser.add_argument("-Mu", "--metrics-user", help="metrics database user")
    parser.add_argument("-MP", "--metrics-password", help="metrics database password")
    parser.add_argument("-Md", "--metrics-db", help="metrics database name")
    return parser


def make_rds_handler_from_args(args: Namespace) -> Union[metrics.RDSHandler, metrics.NullHandler]:
    """
    Creates RDS Handler if all args were passed, in case of metrics off or connection error
    dump handler will be removed.
    :param args: Argparser Namespace object
    :return:
    """
    try:
        connection = rds_connection_factory(
            host=args.metrics_host,
            port=args.metrics_port,
            user=args.metrics_user,
            password=args.metrics_password,
            dbname=args.metrics_db,
        )
    except psycopg2.OperationalError as e:
        if metrics.propagate_exceptions:
            raise e
        else:
            logger.exception("Error while creating RDS connection.")
            return metrics.NullHandler()
    return metrics.RDSHandler(connection)
