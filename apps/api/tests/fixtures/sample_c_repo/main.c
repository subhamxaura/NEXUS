#include "graph.h"
#include "algo.h"
#include <stdio.h>
#include <stdlib.h>

int main(void) {
    Node *head = NULL;
    char buf[64];
    if (scanf("%s", buf) != 1) {
        return 1;
    }
    int *scores = (int *)malloc(10 * sizeof(int));
    if (scores == NULL) {
        return 1;
    }
    scores[0] = algo_hash(buf);
    graph_add(&head, scores[0]);
    system("echo done");
    graph_free(head);
    return 0;
}
