import logging
import colorlog


def get_logger(name):
    # Create a logger
    root_logger = logging.getLogger(name)
    root_logger.setLevel(logging.DEBUG)

    # Create a console handler with a color formatter
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    color_formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s %(module)s %(levelname)-8s: %(message)s%(reset)s",
        datefmt='%Y-%m-%d %H:%M:%S',  # Format for the timestamp
        reset=True,
        log_colors={
            'DEBUG':    'cyan',
            'INFO':     'green',
            'WARNING':  'yellow',
            'ERROR':    'red',
            'CRITICAL': 'red,bg_white',
        },
        secondary_log_colors={},
        style='%'
    )
    console_handler.setFormatter(color_formatter)

    # Add handler to the logger
    root_logger.addHandler(console_handler)

    # Now get the logger for the libraries you want to silence and set its level
    silenced_libraries = [
        'urllib3', 'interactions', 'websockets', 'asyncio', 'requests',
        'matplotlib'

    ]
    for library in silenced_libraries:
        library_logger = logging.getLogger(library)
        library_logger.setLevel(logging.WARNING)
        library_logger.propagate = False

    return root_logger
