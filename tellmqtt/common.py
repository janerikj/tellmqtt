import os


def env_flag(name):
    """True when the environment variable is set to a truthy value.

    1, true, yes and on enable the flag, 0, false, no, off and an unset or
    empty variable disable it.
    """
    return os.environ.get(name, '').strip().lower() not in ('', '0', 'false', 'no', 'off')


class protocoldata:
    def __init__(self, path, values):
        self.path = path
        self.values = values
