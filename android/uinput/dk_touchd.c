/*
 * dk_touchd - virtual touchscreen daemon for the DroidKit container.
 *
 * Creates a uinput multi-touch device that reports itself as the Focaltech
 * controller a Pixel 7 has (name "fts_ts", BUS_I2C), then services a command
 * file so callers can inject taps / swipes / held gestures.
 *
 * Commands (one per line, consumed then the file is truncated):
 *   tap <x> <y> [ms]              press-release at a point
 *   down <x> <y>                  finger down
 *   move <x> <y>                  move while down
 *   up                            finger up
 *   sleep <ms>                    pause between injected steps
 *   swipe <x1> <y1> <x2> <y2> [ms]
 *   quit                          destroy device and exit
 *
 * Build: gcc -static -O2 -o dk_touchd dk_touchd.c
 */
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <linux/uinput.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

#define CMD_FILE "/data/local/tmp/droidkit/touch.cmd"

static int fd = -1;
static int next_tid = 100;

static void emit(int type, int code, int val) {
    struct input_event ie;
    memset(&ie, 0, sizeof ie);
    ie.type = type;
    ie.code = code;
    ie.value = val;
    if (write(fd, &ie, sizeof ie) < 0) perror("write");
}

static void sync_report(void) { emit(EV_SYN, SYN_REPORT, 0); }

static void abs_setup(int code, int min, int max) {
    struct uinput_abs_setup a;
    memset(&a, 0, sizeof a);
    a.code = code;
    a.absinfo.minimum = min;
    a.absinfo.maximum = max;
    if (ioctl(fd, UI_ABS_SETUP, &a) < 0)
        fprintf(stderr, "UI_ABS_SETUP %d: %s\n", code, strerror(errno));
}

static int create_device(void) {
    fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK);
    if (fd < 0) { perror("open /dev/uinput"); return -1; }

    ioctl(fd, UI_SET_EVBIT, EV_SYN);
    ioctl(fd, UI_SET_EVBIT, EV_KEY);
    ioctl(fd, UI_SET_KEYBIT, BTN_TOUCH);
    ioctl(fd, UI_SET_EVBIT, EV_ABS);
    ioctl(fd, UI_SET_ABSBIT, ABS_MT_SLOT);
    ioctl(fd, UI_SET_ABSBIT, ABS_MT_TRACKING_ID);
    ioctl(fd, UI_SET_ABSBIT, ABS_MT_POSITION_X);
    ioctl(fd, UI_SET_ABSBIT, ABS_MT_POSITION_Y);
    ioctl(fd, UI_SET_ABSBIT, ABS_MT_PRESSURE);
    ioctl(fd, UI_SET_ABSBIT, ABS_MT_TOUCH_MAJOR);
    ioctl(fd, UI_SET_PROPBIT, INPUT_PROP_DIRECT);

    struct uinput_setup us;
    memset(&us, 0, sizeof us);
    us.id.bustype = BUS_I2C;
    us.id.vendor = 0x0000;
    us.id.product = 0x0000;
    us.id.version = 0;
    snprintf(us.name, UINPUT_MAX_NAME_SIZE, "fts_ts");
    if (ioctl(fd, UI_DEV_SETUP, &us) < 0) { perror("UI_DEV_SETUP"); return -2; }

    abs_setup(ABS_MT_POSITION_X, 0, 1079);
    abs_setup(ABS_MT_POSITION_Y, 0, 1919);
    abs_setup(ABS_MT_PRESSURE, 0, 255);
    abs_setup(ABS_MT_TOUCH_MAJOR, 0, 255);

    if (ioctl(fd, UI_DEV_CREATE) < 0) { perror("UI_DEV_CREATE"); return -3; }
    return 0;
}

static void finger_down(int x, int y) {
    emit(EV_ABS, ABS_MT_SLOT, 0);
    emit(EV_ABS, ABS_MT_TRACKING_ID, next_tid++);
    emit(EV_ABS, ABS_MT_POSITION_X, x);
    emit(EV_ABS, ABS_MT_POSITION_Y, y);
    emit(EV_ABS, ABS_MT_PRESSURE, 90 + rand() % 30);
    emit(EV_ABS, ABS_MT_TOUCH_MAJOR, 50 + rand() % 15);
    emit(EV_KEY, BTN_TOUCH, 1);
    sync_report();
}

static void finger_move(int x, int y) {
    /* Full frame per step: slot + pressure + contact size alongside the
     * coordinates. Sending bare X/Y frames left InputReader pinned to the
     * press position on this device. */
    emit(EV_ABS, ABS_MT_SLOT, 0);
    emit(EV_ABS, ABS_MT_POSITION_X, x);
    emit(EV_ABS, ABS_MT_POSITION_Y, y);
    emit(EV_ABS, ABS_MT_PRESSURE, 90 + rand() % 30);
    emit(EV_ABS, ABS_MT_TOUCH_MAJOR, 50 + rand() % 15);
    sync_report();
}

static void finger_up(void) {
    emit(EV_ABS, ABS_MT_TRACKING_ID, -1);
    emit(EV_KEY, BTN_TOUCH, 0);
    sync_report();
}

static void do_swipe(int x1, int y1, int x2, int y2, int ms) {
    if (ms < 20) ms = 200;
    int steps = ms / 8;
    if (steps < 4) steps = 4;
    finger_down(x1, y1);
    for (int i = 1; i <= steps; i++) {
        double t = (double)i / steps;
        /* ease-in-out: matches how a thumb actually accelerates */
        double e = t < 0.5 ? 2 * t * t : 1 - pow(-2 * t + 2, 2) / 2;
        finger_move((int)lround(x1 + (x2 - x1) * e), (int)lround(y1 + (y2 - y1) * e));
        usleep(ms * 1000 / steps);
    }
    finger_up();
}

static void handle_line(char *line) {
    char cmd[32] = {0};
    int a = 0, b = 0, c = 0, d = 0, e = 0;
    int n = sscanf(line, "%31s %d %d %d %d %d", cmd, &a, &b, &c, &d, &e);
    if (n < 1) return;
    if (!strcmp(cmd, "tap") && n >= 3) {
        int hold = n >= 4 ? c : 80;
        finger_down(a, b);
        usleep(hold * 1000);
        finger_up();
    } else if (!strcmp(cmd, "down") && n >= 3) {
        finger_down(a, b);
    } else if (!strcmp(cmd, "move") && n >= 3) {
        finger_move(a, b);
    } else if (!strcmp(cmd, "up")) {
        finger_up();
    } else if (!strcmp(cmd, "swipe") && n >= 5) {
        do_swipe(a, b, c, d, n >= 6 ? e : 220);
    } else if (!strcmp(cmd, "sleep") && n >= 2) {
        if (a > 0) usleep(a * 1000);
    } else if (!strcmp(cmd, "quit")) {
        ioctl(fd, UI_DEV_DESTROY);
        close(fd);
        exit(0);
    }
}

int main(void) {
    srand((unsigned)getpid() ^ (unsigned)time(NULL));
    if (create_device() != 0) return 1;
    printf("created\n");
    fflush(stdout);

    for (;;) {
        FILE *f = fopen(CMD_FILE, "r");
        if (f) {
            char line[256];
            int any = 0;
            while (fgets(line, sizeof line, f)) {
                char *nl = strchr(line, '\n');
                if (nl) *nl = 0;
                if (*line) { handle_line(line); any = 1; }
            }
            fclose(f);
            /* Consume the batch by unlinking it: writers publish with an atomic
             * rename, so truncating here would race with the next batch. */
            if (any) unlink(CMD_FILE);
        }
        usleep(100 * 1000);
    }
    return 0;
}
