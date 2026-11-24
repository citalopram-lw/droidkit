/*
 * uinput probe: create a virtual multi-touch screen named "fts_ts"
 * (Focaltech, BUS_I2C - what a Pixel 7 reports) and send one tap.
 * Static build so it runs on the Android container without a libc.
 */
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <linux/uinput.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

static void emit(int fd, int type, int code, int val) {
    struct input_event ie;
    memset(&ie, 0, sizeof ie);
    ie.type = type; ie.code = code; ie.value = val;
    if (write(fd, &ie, sizeof ie) < 0) perror("write");
}

static void abs_setup(int fd, int code, int min, int max, int fuzz, int flat) {
    struct uinput_abs_setup a;
    memset(&a, 0, sizeof a);
    a.code = code;
    a.absinfo.minimum = min;
    a.absinfo.maximum = max;
    a.absinfo.fuzz = fuzz;
    a.absinfo.flat = flat;
    if (ioctl(fd, UI_ABS_SETUP, &a) < 0) fprintf(stderr, "UI_ABS_SETUP %d: %s\n", code, strerror(errno));
}

int main(int argc, char **argv) {
    int fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK);
    if (fd < 0) { perror("open /dev/uinput"); return 1; }

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
    us.id.vendor  = 0x0000;
    us.id.product = 0x0000;
    us.id.version = 0;
    snprintf(us.name, UINPUT_MAX_NAME_SIZE, "fts_ts");
    if (ioctl(fd, UI_DEV_SETUP, &us) < 0) { perror("UI_DEV_SETUP"); return 2; }

    abs_setup(fd, ABS_MT_POSITION_X, 0, 1079, 0, 0);
    abs_setup(fd, ABS_MT_POSITION_Y, 0, 1919, 0, 0);
    abs_setup(fd, ABS_MT_PRESSURE,   0, 255, 0, 0);
    abs_setup(fd, ABS_MT_TOUCH_MAJOR,0, 255, 0, 0);

    if (ioctl(fd, UI_DEV_CREATE) < 0) { perror("UI_DEV_CREATE"); return 3; }
    printf("created\n"); fflush(stdout);

    int x = argc > 1 ? atoi(argv[1]) : 540;
    int y = argc > 2 ? atoi(argv[2]) : 960;
    sleep(3);

    emit(fd, EV_ABS, ABS_MT_SLOT, 0);
    emit(fd, EV_ABS, ABS_MT_TRACKING_ID, 4242);
    emit(fd, EV_ABS, ABS_MT_POSITION_X, x - 2);
    emit(fd, EV_ABS, ABS_MT_POSITION_Y, y + 1);
    emit(fd, EV_ABS, ABS_MT_PRESSURE, 96);
    emit(fd, EV_ABS, ABS_MT_TOUCH_MAJOR, 58);
    emit(fd, EV_KEY, BTN_TOUCH, 1);
    emit(fd, EV_SYN, SYN_REPORT, 0);
    usleep(70000);
    emit(fd, EV_ABS, ABS_MT_POSITION_X, x);
    emit(fd, EV_ABS, ABS_MT_POSITION_Y, y);
    emit(fd, EV_SYN, SYN_REPORT, 0);
    usleep(40000);
    emit(fd, EV_ABS, ABS_MT_TRACKING_ID, -1);
    emit(fd, EV_KEY, BTN_TOUCH, 0);
    emit(fd, EV_SYN, SYN_REPORT, 0);
    printf("tap %d,%d sent\n", x, y); fflush(stdout);

    int hold = argc > 3 ? atoi(argv[3]) : 25;
    sleep(hold);
    ioctl(fd, UI_DEV_DESTROY);
    close(fd);
    return 0;
}
