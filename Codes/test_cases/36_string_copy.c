int main() {
    char target[20];
    char source[] = "Copy This";
    int i = 0;
    while(source[i] != '\0') {
        target[i] = source[i];
        i++;
    }
    target[i] = '\0';
    return target[0];
}