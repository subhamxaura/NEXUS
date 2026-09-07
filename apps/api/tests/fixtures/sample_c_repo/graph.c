#include "graph.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int counter = 0;

int graph_add(Node **head, int id) {
    Node *n = (Node *)malloc(sizeof(Node));
    if (n == NULL) {
        return -1;
    }
    n->id = id;
    n->next = *head;
    *head = n;
    counter++;
    return 0;
}

void graph_free(Node *head) {
    Node *cur = head;
    while (cur != NULL) {
        Node *tmp = cur;
        cur = cur->next;
        free(tmp);
    }
}

int graph_classify(int v, int mode) {
    int r = 0;
    if (mode == 1) { r = v; }
    else if (mode == 2) { r = v * 2; }
    else if (mode == 3) { r = v * 3; }
    else { r = -v; }
    for (int i = 0; i < v; i++) {
        if (i % 2 == 0 && r > 0) { r += i; }
        else if (i % 3 == 0 || r < 0) { r -= i; }
        else { r += 1; }
    }
    while (r > 100) { r -= 10; }
    switch (mode) {
        case 1: r += 1; break;
        case 2: r += 2; break;
        default: break;
    }
    return r;
}

void graph_label(char *dst, const char *src) {
    strcpy(dst, src);
}
