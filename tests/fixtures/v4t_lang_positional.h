/* The older generator wrote this shape. Kept in the tree because two
 * products still build against it. */
#ifndef V4T_LANG_OLD_H
#define V4T_LANG_OLD_H

typedef enum {
    LNG_PRINT_STARTED = 0,
    LNG_PRINT_STOPPED,
    LNG_PURGE_SETTINGS,
    LNG_COUNT
} lang_id_t;

static const char * const lng_en[LNG_COUNT] = {
    "Print started",
    "Print stopped",
    "Purge Settings",
};

#endif
