"""Readers that turn a product's own string format into catalog messages.

Three dialects have to be understood, because the product family never agreed
on one:

``rc``
    The Win32 resource script behind V4T-TIJ and V4T-TIJ8PEN-Config.
``cheader``
    The generated C string table the V4T-Mini panel firmware links against.
``androidxml``
    ``res/values/strings.xml`` from V4T-Mobile.
"""
