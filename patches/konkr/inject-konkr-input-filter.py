#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit(f"usage: {sys.argv[0]} <0058-patch>")

path = Path(sys.argv[1])
text = path.read_text()


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)

replace_once(
    "+#define MCU_TRIG_MAX\t\t255\n",
    "+#define MCU_TRIG_MAX\t\t255\n"
    "+\n"
    "+/* Pocket FIT Elite Hall-interference workaround. */\n"
    "+static unsigned int r3_debounce_ms = 50;\n"
    "+module_param(r3_debounce_ms, uint, 0644);\n"
    "+MODULE_PARM_DESC(r3_debounce_ms,\n"
    "+\t\t \"Minimum R3 press duration in ms before reporting it (0 disables)\");\n"
    "+\n"
    "+static unsigned int trigger_confirm_frames = 2;\n"
    "+module_param(trigger_confirm_frames, uint, 0644);\n"
    "+MODULE_PARM_DESC(trigger_confirm_frames,\n"
    "+\t\t \"Consecutive non-zero trigger frames required before reporting (1 disables)\");\n",
    "trigger parameters",
)

replace_once(
    "+\tunsigned int reinit_fails;\n+\tbool dead;\n+};\n",
    "+\tunsigned int reinit_fails;\n"
    "+\tbool dead;\n"
    "+\tunsigned int trig_left_nonzero_frames;\n"
    "+\tunsigned int trig_right_nonzero_frames;\n"
    "+\tbool r3_raw_down;\n"
    "+\tbool r3_reported_down;\n"
    "+\tunsigned long r3_down_since;\n"
    "+};\n",
    "driver state",
)

helpers = r'''+/*
+ * Suppress a trigger that is non-zero for only one MCU frame. This only
+ * delays activation: once confirmed, the raw analog value is passed through
+ * unchanged. A return to zero is always reported immediately.
+ */
+static u8 mcu_filter_trigger(u8 raw, unsigned int *nonzero_frames)
+{
+	unsigned int required = trigger_confirm_frames;
+
+	if (!raw) {
+		*nonzero_frames = 0;
+		return 0;
+	}
+
+	if (required <= 1)
+		return raw;
+
+	if (*nonzero_frames < required)
+		(*nonzero_frames)++;
+
+	if (*nonzero_frames < required)
+		return 0;
+
+	return raw;
+}
+
+/*
+ * R3 is a digital bit in the MCU key bitmap. Do not expose it until the raw
+ * bit has stayed asserted for the configured interval. Short pulses then
+ * disappear completely instead of becoming clicks in userspace.
+ */
+static void mcu_report_r3(struct mcu_joystick *mcu, bool down)
+{
+	unsigned int debounce = r3_debounce_ms;
+
+	if (!down) {
+		mcu->r3_raw_down = false;
+		if (mcu->r3_reported_down)
+			input_report_key(mcu->input, BTN_THUMBR, 0);
+		mcu->r3_reported_down = false;
+		return;
+	}
+
+	if (!mcu->r3_raw_down) {
+		mcu->r3_raw_down = true;
+		mcu->r3_down_since = jiffies;
+	}
+
+	if (!mcu->r3_reported_down &&
+	    (!debounce ||
+	     time_after_eq(jiffies, mcu->r3_down_since +
+				      msecs_to_jiffies(debounce)))) {
+		input_report_key(mcu->input, BTN_THUMBR, 1);
+		mcu->r3_reported_down = true;
+	}
+}
+
'''
replace_once(
    "+static void mcu_report(struct mcu_joystick *mcu, const u16 regs[MCU_NREGS])\n",
    helpers + "+static void mcu_report(struct mcu_joystick *mcu, const u16 regs[MCU_NREGS])\n",
    "report helpers",
)

replace_once(
    "+\tu16 key = regs[MCU_FRAME_KEY];\n+\tint i;\n",
    "+\tu16 key = regs[MCU_FRAME_KEY];\n+\tu8 left_trigger, right_trigger;\n+\tint i;\n",
    "report locals",
)

replace_once(
    "+\tinput_report_abs(in, ABS_Z,  regs[MCU_FRAME_TRIG] & 0xff);\n"
    "+\tinput_report_abs(in, ABS_RZ, regs[MCU_FRAME_TRIG] >> 8);\n"
    "+\tinput_report_key(in, BTN_TL2, (regs[MCU_FRAME_TRIG] & 0xff) == 0xff);\n"
    "+\tinput_report_key(in, BTN_TR2, (regs[MCU_FRAME_TRIG] >> 8) == 0xff);\n",
    "+\tleft_trigger = mcu_filter_trigger(regs[MCU_FRAME_TRIG] & 0xff,\n"
    "+\t\t\t\t\t &mcu->trig_left_nonzero_frames);\n"
    "+\tright_trigger = mcu_filter_trigger(regs[MCU_FRAME_TRIG] >> 8,\n"
    "+\t\t\t\t\t  &mcu->trig_right_nonzero_frames);\n"
    "+\tinput_report_abs(in, ABS_Z, left_trigger);\n"
    "+\tinput_report_abs(in, ABS_RZ, right_trigger);\n"
    "+\tinput_report_key(in, BTN_TL2, left_trigger == 0xff);\n"
    "+\tinput_report_key(in, BTN_TR2, right_trigger == 0xff);\n",
    "trigger reporting",
)

replace_once(
    "+\tfor (i = 0; i < ARRAY_SIZE(mcu_btn_map); i++)\n"
    "+\t\tinput_report_key(in, mcu_btn_map[i].code,\n"
    "+\t\t\t\t !!(key & BIT(mcu_btn_map[i].bit)));\n",
    "+\tfor (i = 0; i < ARRAY_SIZE(mcu_btn_map); i++) {\n"
    "+\t\tif (mcu_btn_map[i].code == BTN_THUMBR)\n"
    "+\t\t\tcontinue;\n"
    "+\t\tinput_report_key(in, mcu_btn_map[i].code,\n"
    "+\t\t\t\t !!(key & BIT(mcu_btn_map[i].bit)));\n"
    "+\t}\n"
    "+\n"
    "+\tmcu_report_r3(mcu, !!(key & BIT(11)));\n",
    "R3 reporting",
)

replace_once(
    "+\tfor (i = 0; i < ARRAY_SIZE(mcu_btn_map); i++)\n"
    "+\t\tinput_report_key(in, mcu_btn_map[i].code, 0);\n"
    "+\tinput_sync(in);\n"
    "+}\n"
    "+\n"
    "+/* returns true if the frame header validated */\n",
    "+\tfor (i = 0; i < ARRAY_SIZE(mcu_btn_map); i++)\n"
    "+\t\tinput_report_key(in, mcu_btn_map[i].code, 0);\n"
    "+\tinput_sync(in);\n"
    "+\n"
    "+\tmcu->trig_left_nonzero_frames = 0;\n"
    "+\tmcu->trig_right_nonzero_frames = 0;\n"
    "+\tmcu->r3_raw_down = false;\n"
    "+\tmcu->r3_reported_down = false;\n"
    "+}\n"
    "+\n"
    "+/* returns true if the frame header validated */\n",
    "idle reset",
)

path.write_text(text)
print(f"Injected KONKR input filter into {path}")
