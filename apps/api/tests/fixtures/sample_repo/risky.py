"""Deterministic risk hotspot with an insecure pattern and no tests."""

import os
import pickle
import subprocess


def handle_request(user_input, mode, flag_a, flag_b, flag_c, extra=None):
    if mode == "a":
        result = eval(user_input)
    elif mode == "b":
        if flag_a and flag_b:
            result = pickle.loads(user_input)
        elif flag_a or flag_b or flag_c:
            result = str(user_input)
        else:
            result = repr(user_input)
    elif mode == "c":
        for i in range(10):
            while flag_a:
                if extra:
                    break
                flag_a = False
            result = i
    else:
        try:
            result = subprocess.Popen(user_input, shell=True)
        except Exception:
            result = None
    assert result is not None
    return result


def tiny():
    return os.path.join("a", "b")
