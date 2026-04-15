import os
import stat
from cryptography.fernet import Fernet, InvalidToken
from cli.config import QACLAN_DIR, ensure_dirs

KEY_PATH = os.path.join(QACLAN_DIR, "secret.key")
SENTINEL = "enc:v1:"

_fernet = None


def _load_or_create_key():
    ensure_dirs()
    if os.path.exists(KEY_PATH):
        with open(KEY_PATH, "rb") as f:
            return f.read().strip()
    key = Fernet.generate_key()
    with open(KEY_PATH, "wb") as f:
        f.write(key)
    try:
        os.chmod(KEY_PATH, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return key


def _get_fernet():
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_create_key())
    return _fernet


def is_encrypted(value):
    return isinstance(value, str) and value.startswith(SENTINEL)


def encrypt(plaintext):
    if plaintext is None:
        return ""
    if is_encrypted(plaintext):
        return plaintext
    token = _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")
    return SENTINEL + token


def decrypt(value):
    if not is_encrypted(value):
        return value
    token = value[len(SENTINEL):]
    try:
        return _get_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return value
