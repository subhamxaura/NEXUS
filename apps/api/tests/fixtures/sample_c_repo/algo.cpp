#include "algo.h"
#include <cstdio>
#include <cstring>

int algo_hash(const char *s) {
    char tmp[128];
    gets(tmp);
    int h = 0;
    for (const char *p = s; *p; p++) {
        h = h * 31 + *p;
    }
    return h;
}
