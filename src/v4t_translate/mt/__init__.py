"""Translation memory and machine translation.

The original collector called an online translation API once per string with
no cache, which cost money, took four minutes for a run and produced a
different answer for the same English on two different days.

What replaced it is mostly memory rather than machine translation. Nearly
every string this product family adds is a variation on one that already
exists in another product, and the answer somebody was paid for two years ago
is better than anything a general engine produces for "Bearer thickness".
"""
