"""Production entry point."""
import os
from waitress import serve
from . import create_app


HOST = os.environ.get('FACTORY_UI_HOST', '127.0.0.1')


def main():
    serve(create_app(), host=HOST, port=8300, threads=8)


if __name__ == '__main__':
    main()
