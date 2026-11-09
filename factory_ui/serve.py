"""Production entry point; never bind outside loopback."""
from waitress import serve
from . import create_app


def main():
    serve(create_app(), host='127.0.0.1', port=8300, threads=8)


if __name__ == '__main__':
    main()
