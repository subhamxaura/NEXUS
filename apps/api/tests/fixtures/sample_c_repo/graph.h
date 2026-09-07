#ifndef GRAPH_H
#define GRAPH_H

typedef struct Node {
    int id;
    struct Node *next;
} Node;

int graph_add(Node **head, int id);
void graph_free(Node *head);
int graph_classify(int v, int mode);
void graph_label(char *dst, const char *src);

#endif
