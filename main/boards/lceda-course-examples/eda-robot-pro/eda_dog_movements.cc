#include "eda_dog_movements.h"

#include <algorithm>
#include <cmath>

#include "oscillator.h"

static const char *TAG = "EDARobotDogMovements";

#define LEG_HOME_POSITION 90

EDARobotDog::EDARobotDog() {
  is_dog_resting_ = false;
  // Initialize all servo pins to -1 (not connected)
  for (int i = 0; i < SERVO_COUNT; i++) {
    servo_pins_[i] = -1;
    servo_trim_[i] = 0;
  }
}

EDARobotDog::~EDARobotDog() { DetachServos(); }

unsigned long IRAM_ATTR millis() {
  return (unsigned long)(esp_timer_get_time() / 1000ULL);
}

void EDARobotDog::Init(int left_front_leg, int left_rear_leg, int right_front_leg,
                  int right_rear_leg) {
  servo_pins_[LEFT_FRONT_LEG] = left_front_leg;
  servo_pins_[LEFT_REAR_LEG] = left_rear_leg;
  servo_pins_[RIGHT_FRONT_LEG] = right_front_leg;
  servo_pins_[RIGHT_REAR_LEG] = right_rear_leg;

  AttachServos();
  is_dog_resting_ = false;
}

///////////////////////////////////////////////////////////////////
//-- ATTACH & DETACH FUNCTIONS ----------------------------------//
///////////////////////////////////////////////////////////////////
void EDARobotDog::AttachServos() {
  for (int i = 0; i < SERVO_COUNT; i++) {
    if (servo_pins_[i] != -1) {
      servo_[i].Attach(servo_pins_[i]);
    }
  }
}

void EDARobotDog::DetachServos() {
  for (int i = 0; i < SERVO_COUNT; i++) {
    if (servo_pins_[i] != -1) {
      servo_[i].Detach();
    }
  }
}

///////////////////////////////////////////////////////////////////
//-- OSCILLATORS TRIMS ------------------------------------------//
///////////////////////////////////////////////////////////////////
void EDARobotDog::SetTrims(int left_front_leg, int left_rear_leg,
                      int right_front_leg, int right_rear_leg) {
  servo_trim_[LEFT_FRONT_LEG] = left_front_leg;
  servo_trim_[LEFT_REAR_LEG] = left_rear_leg;
  servo_trim_[RIGHT_FRONT_LEG] = right_front_leg;
  servo_trim_[RIGHT_REAR_LEG] = right_rear_leg;

  for (int i = 0; i < SERVO_COUNT; i++) {
    if (servo_pins_[i] != -1) {
      servo_[i].SetTrim(servo_trim_[i]);
    }
  }
}

///////////////////////////////////////////////////////////////////
//-- BASIC MOTION FUNCTIONS -------------------------------------//
///////////////////////////////////////////////////////////////////
void EDARobotDog::MoveServos(int time, int servo_target[]) {
  if (GetRestState() == true) {
    SetRestState(false);
  }

  final_time_ = millis() + time;
  if (time > 10) {
    for (int i = 0; i < SERVO_COUNT; i++) {
      if (servo_pins_[i] != -1) {
        increment_[i] =
            (servo_target[i] - servo_[i].GetPosition()) / (time / 10.0);
      }
    }

    for (int iteration = 1; millis() < final_time_; iteration++) {
      partial_time_ = millis() + 10;
      for (int i = 0; i < SERVO_COUNT; i++) {
        if (servo_pins_[i] != -1) {
          servo_[i].SetPosition(servo_[i].GetPosition() + increment_[i]);
        }
      }
      vTaskDelay(pdMS_TO_TICKS(10));
    }
  } else {
    for (int i = 0; i < SERVO_COUNT; i++) {
      if (servo_pins_[i] != -1) {
        servo_[i].SetPosition(servo_target[i]);
      }
    }
    vTaskDelay(pdMS_TO_TICKS(time));
  }

  // final adjustment to the target.
  bool f = true;
  int adjustment_count = 0;
  while (f && adjustment_count < 10) {
    f = false;
    for (int i = 0; i < SERVO_COUNT; i++) {
      if (servo_pins_[i] != -1 && servo_target[i] != servo_[i].GetPosition()) {
        f = true;
        break;
      }
    }
    if (f) {
      for (int i = 0; i < SERVO_COUNT; i++) {
        if (servo_pins_[i] != -1) {
          servo_[i].SetPosition(servo_target[i]);
        }
      }
      vTaskDelay(pdMS_TO_TICKS(10));
      adjustment_count++;
    }
  };
}

void EDARobotDog::MoveSingle(int position, int servo_number) {
  if (position > 180)
    position = 90;
  if (position < 0)
    position = 90;

  if (GetRestState() == true) {
    SetRestState(false);
  }

  if (servo_number >= 0 && servo_number < SERVO_COUNT &&
      servo_pins_[servo_number] != -1) {
    servo_[servo_number].SetPosition(position);
  }
}

void EDARobotDog::OscillateServos(int amplitude[SERVO_COUNT],
                             int offset[SERVO_COUNT], int period,
                             double phase_diff[SERVO_COUNT], float cycle = 1) {
  for (int i = 0; i < SERVO_COUNT; i++) {
    if (servo_pins_[i] != -1) {
      servo_[i].SetO(offset[i]);
      servo_[i].SetA(amplitude[i]);
      servo_[i].SetT(period);
      servo_[i].SetPh(phase_diff[i]);
    }
  }

  double ref = millis();
  double end_time = period * cycle + ref;

  while (millis() < end_time) {
    for (int i = 0; i < SERVO_COUNT; i++) {
      if (servo_pins_[i] != -1) {
        servo_[i].Refresh();
      }
    }
    vTaskDelay(5);
  }
  vTaskDelay(pdMS_TO_TICKS(10));
}

void EDARobotDog::Execute(int amplitude[SERVO_COUNT], int offset[SERVO_COUNT],
                     int period, double phase_diff[SERVO_COUNT],
                     float steps = 1.0) {
  if (GetRestState() == true) {
    SetRestState(false);
  }

  int cycles = (int)steps;

  //-- Execute complete cycles
  if (cycles >= 1)
    for (int i = 0; i < cycles; i++)
      OscillateServos(amplitude, offset, period, phase_diff);

  //-- Execute the final not complete cycle
  OscillateServos(amplitude, offset, period, phase_diff, (float)steps - cycles);
  vTaskDelay(pdMS_TO_TICKS(10));
}

///////////////////////////////////////////////////////////////////
//-- HOME = Dog at rest position --------------------------------//
///////////////////////////////////////////////////////////////////
void EDARobotDog::Home() {
  if (is_dog_resting_ == false) { // Go to rest position only if necessary
    int homes[SERVO_COUNT] = {LEG_HOME_POSITION, LEG_HOME_POSITION,
                              LEG_HOME_POSITION, LEG_HOME_POSITION};
    MoveServos(500, homes);
    is_dog_resting_ = true;
  }
  vTaskDelay(pdMS_TO_TICKS(200));
}

bool EDARobotDog::GetRestState() { return is_dog_resting_; }

void EDARobotDog::SetRestState(bool state) { is_dog_resting_ = state; }

///////////////////////////////////////////////////////////////////
//-- BASIC LEG MOVEMENTS ----------------------------------------//
///////////////////////////////////////////////////////////////////

void EDARobotDog::LiftLeftFrontLeg(int period, int height) {

  // Get current positions
  int current_pos[SERVO_COUNT];
  for (int i = 0; i < SERVO_COUNT; i++) {
    if (servo_pins_[i] != -1) {
      current_pos[i] = servo_[i].GetPosition();
    } else {
      current_pos[i] = LEG_HOME_POSITION;
    }
  }

  // Repeat swing action 3 times
  for (int num = 0; num < 3; num++) {
    // servo1.write(180); delay(100);
    current_pos[LEFT_FRONT_LEG] = 0; // servo1
    MoveServos(100, current_pos);

    // servo1.write(150); delay(100);
    current_pos[LEFT_FRONT_LEG] = 30; // servo1
    MoveServos(100, current_pos);
  }

  // servo1.write(90);
  current_pos[LEFT_FRONT_LEG] = 90; // servo1
  MoveServos(100, current_pos);
}

void EDARobotDog::LiftLeftRearLeg(int period, int height) {

  // Get current positions
  int current_pos[SERVO_COUNT];
  for (int i = 0; i < SERVO_COUNT; i++) {
    if (servo_pins_[i] != -1) {
      current_pos[i] = servo_[i].GetPosition();
    } else {
      current_pos[i] = LEG_HOME_POSITION;
    }
  }

  // Repeat swing action 3 times
  for (int num = 0; num < 3; num++) {
    // servo1.write(180); delay(100);
    current_pos[LEFT_REAR_LEG] = 180; // servo1
    MoveServos(100, current_pos);

    // servo1.write(150); delay(100);
    current_pos[LEFT_REAR_LEG] = 150; // servo1
    MoveServos(100, current_pos);
  }

  // servo1.write(90);
  current_pos[LEFT_REAR_LEG] = 90; // servo1
  MoveServos(100, current_pos);
}

void EDARobotDog::LiftRightFrontLeg(int period, int height) {

  // Get current positions
  int current_pos[SERVO_COUNT];
  for (int i = 0; i < SERVO_COUNT; i++) {
    if (servo_pins_[i] != -1) {
      current_pos[i] = servo_[i].GetPosition();
    } else {
      current_pos[i] = LEG_HOME_POSITION;
    }
  }

  // Repeat swing action 3 times
  for (int num = 0; num < 3; num++) {
    // servo1.write(180); delay(100);
    current_pos[RIGHT_FRONT_LEG] = 180; // servo1
    MoveServos(100, current_pos);

    // servo1.write(150); delay(100);
    current_pos[RIGHT_FRONT_LEG] = 150; // servo1
    MoveServos(100, current_pos);
  }

  // servo1.write(90);
  current_pos[RIGHT_FRONT_LEG] = 90; // servo1
  MoveServos(100, current_pos);
}

void EDARobotDog::LiftRightRearLeg(int period, int height) {

  // Get current positions
  int current_pos[SERVO_COUNT];
  for (int i = 0; i < SERVO_COUNT; i++) {
    if (servo_pins_[i] != -1) {
      current_pos[i] = servo_[i].GetPosition();
    } else {
      current_pos[i] = LEG_HOME_POSITION;
    }
  }

  // Repeat swing action 3 times
  for (int num = 0; num < 3; num++) {
    // servo1.write(180); delay(100);
    current_pos[RIGHT_REAR_LEG] = 0; // servo1
    MoveServos(100, current_pos);

    // servo1.write(150); delay(100);
    current_pos[RIGHT_REAR_LEG] = 30; // servo1
    MoveServos(100, current_pos);
  }

  // servo1.write(90);
  current_pos[RIGHT_FRONT_LEG] = 90; // servo1
  MoveServos(100, current_pos);
}

///////////////////////////////////////////////////////////////////
//-- DOG GAIT MOVEMENTS -----------------------------------------//
///////////////////////////////////////////////////////////////////

// Servo direction analysis (front/back physical directions inferred from Stretch/Sleep):
//
//   Stretch: LF=0, LR=180, RF=180, RR=0
//   -> front legs extend forward, rear legs extend backward
//
//   LEFT_FRONT_LEG  (0): decrease=forward, increase=backward
//   LEFT_REAR_LEG   (1): decrease=forward, increase=backward
//   RIGHT_FRONT_LEG (2): increase=forward, decrease=backward
//   RIGHT_REAR_LEG  (3): increase=forward, decrease=backward
//
//   i.e. left legs share sign (decrease=forward), right legs share sign (increase=forward)
//   Diagonal A: left-front + right-rear -> both decrease when walking forward (each "forward")
//   Diagonal B: left-rear + right-front -> left-rear decreases, right-front increases (each "forward")
//
//   Leg lift direction (from the Lift functions):
//   LEFT_FRONT_LEG:  0   (decrease = lift)
//   LEFT_REAR_LEG:   180 (increase = lift)
//   RIGHT_FRONT_LEG: 180 (increase = lift)
//   RIGHT_REAR_LEG:  0   (decrease = lift)

// Helper: fetch the current positions of all servos
void EDARobotDog::GetCurrentPositions(int pos[SERVO_COUNT]) {
  for (int i = 0; i < SERVO_COUNT; i++) {
    if (servo_pins_[i] != -1) {
      pos[i] = servo_[i].GetPosition();
    } else {
      pos[i] = LEG_HOME_POSITION;
    }
  }
}

void EDARobotDog::Turn(float steps, int period, int dir) {
  if (GetRestState() == true) {
    SetRestState(false);
  }

  // Turning = left side backs up + right side moves forward (left turn), or the reverse (right turn)
  // Derived from the verified Walk directions:
  //   Forward: LF=90-s, LR=90-s, RF=90+s, RR=90+s
  //   Backward: LF=90+s, LR=90+s, RF=90-s, RR=90-s
  //
  // Left turn (d=1): left side backward + right side forward
  //   LF=90+s, LR=90+s, RF=90+s, RR=90+s -> all 90+s
  //   Ground push-back: all 90-s
  //
  // Right turn (d=-1): left side forward + right side backward
  //   LF=90-s, LR=90-s, RF=90-s, RR=90-s -> all 90-s
  //   Ground push-back: all 90+s

  const int swing = 60;
  const int lift = 25;
  int t = period / 6;
  if (t < 50) t = 50;

  int d = (dir == LEFT) ? -1 : 1;

  for (int step = 0; step < (int)steps; step++) {
    int pos[SERVO_COUNT];
    GetCurrentPositions(pos);

    // Beat 1: lift diagonal A (LF+RR)
    pos[LEFT_FRONT_LEG]  = 90 - lift;
    pos[RIGHT_REAR_LEG]  = 90 - lift;
    MoveServos(t, pos);

    // Beat 2: A swings in the air + B pushes against the ground
    pos[LEFT_FRONT_LEG]  = 90 - lift + d * swing;  // LF in air
    pos[RIGHT_REAR_LEG]  = 90 - lift + d * swing;  // RR in air
    pos[LEFT_REAR_LEG]   = 90 - d * swing;         // LR ground push-back
    pos[RIGHT_FRONT_LEG] = 90 - d * swing;         // RF ground push-back
    MoveServos(t, pos);

    // Beat 3: put A down
    pos[LEFT_FRONT_LEG]  = 90 + d * swing;
    pos[RIGHT_REAR_LEG]  = 90 + d * swing;
    MoveServos(t / 2, pos);

    // Beat 4: lift diagonal B (LR+RF)
    pos[LEFT_REAR_LEG]   = 90 + lift;
    pos[RIGHT_FRONT_LEG] = 90 + lift;
    MoveServos(t, pos);

    // Beat 5: B swings in the air + A pushes against the ground
    pos[LEFT_REAR_LEG]   = 90 + lift + d * swing;  // LR in air
    pos[RIGHT_FRONT_LEG] = 90 + lift + d * swing;  // RF in air
    pos[LEFT_FRONT_LEG]  = 90 - d * swing;         // LF ground push-back
    pos[RIGHT_REAR_LEG]  = 90 - d * swing;         // RR ground push-back
    MoveServos(t, pos);

    // Beat 6: put B down
    pos[LEFT_REAR_LEG]   = 90 + d * swing;
    pos[RIGHT_FRONT_LEG] = 90 + d * swing;
    MoveServos(t / 2, pos);
  }

  // Return to center at the end
  int home[SERVO_COUNT] = {90, 90, 90, 90};
  MoveServos(150, home);
}

void EDARobotDog::Walk(float steps, int period, int dir) {
  if (GetRestState() == true) {
    SetRestState(false);
  }

  // Trot diagonal gait
  // Direction: LF-=forward, LR-=forward, RF+=forward, RR+=forward
  // Lift: LF-=lift, LR+=lift, RF+=lift, RR-=lift

  const int lift = 25;
  const int swing = 30;
  int t = period / 6;
  if (t < 50) t = 50;

  int fwd = (dir == FORWARD) ? 1 : -1;

  for (int step = 0; step < (int)steps; step++) {
    int pos[SERVO_COUNT];
    GetCurrentPositions(pos);

    // Beat 1: lift diagonal A (LF+RR)
    pos[LEFT_FRONT_LEG]  = 90 - lift;
    pos[RIGHT_REAR_LEG]  = 90 - lift;
    MoveServos(t, pos);

    // Beat 2: A swings forward in air + B pushes ground backward (simultaneously)
    pos[LEFT_FRONT_LEG]  = 90 - lift - fwd * swing;  // LF: stay lifted + swing forward
    pos[RIGHT_REAR_LEG]  = 90 - lift + fwd * swing;  // RR: stay lifted + swing forward (increase=forward)
    pos[LEFT_REAR_LEG]   = 90 + fwd * swing;         // LR: ground push-back (increase=backward)
    pos[RIGHT_FRONT_LEG] = 90 - fwd * swing;         // RF: ground push-back (decrease=backward)
    MoveServos(t, pos);

    // Beat 3: set A down (touch down at forward-swing position)
    pos[LEFT_FRONT_LEG]  = 90 - fwd * swing;
    pos[RIGHT_REAR_LEG]  = 90 + fwd * swing;
    MoveServos(t / 2, pos);

    // Beat 4: lift diagonal B (LR+RF)
    pos[LEFT_REAR_LEG]   = 90 + lift;
    pos[RIGHT_FRONT_LEG] = 90 + lift;
    MoveServos(t, pos);

    // Beat 5: B swings forward in air + A pushes ground backward (simultaneously)
    pos[LEFT_REAR_LEG]   = 90 + lift - fwd * swing;  // LR: stay lifted + swing forward (decrease=forward)
    pos[RIGHT_FRONT_LEG] = 90 + lift + fwd * swing;  // RF: stay lifted + swing forward (increase=forward)
    pos[LEFT_FRONT_LEG]  = 90 + fwd * swing;         // LF: ground push-back (increase=backward)
    pos[RIGHT_REAR_LEG]  = 90 - fwd * swing;         // RR: ground push-back (decrease=backward)
    MoveServos(t, pos);

    // Beat 6: set B down (no re-center, chain into the next step)
    pos[LEFT_REAR_LEG]   = 90 - fwd * swing;
    pos[RIGHT_FRONT_LEG] = 90 + fwd * swing;
    MoveServos(t / 2, pos);
  }

  // Return to center at the end
  int home[SERVO_COUNT] = {90, 90, 90, 90};
  MoveServos(150, home);
}

void EDARobotDog::Sit(int period) {


int current_pos[SERVO_COUNT];
      for (int i = 0; i < SERVO_COUNT; i++) {
        if (servo_pins_[i] != -1) {
          current_pos[i] = servo_[i].GetPosition();
        } else {
          current_pos[i] = LEG_HOME_POSITION;
        }
      }


  current_pos[LEFT_REAR_LEG] = 0;  // servo2
  current_pos[RIGHT_REAR_LEG] = 180; // servo4
  MoveServos(100, current_pos);
}

void EDARobotDog::Stand(int period) {
  // Stand: return all legs to the neutral position
  Home();
}

void EDARobotDog::Stretch(int period) {


  // Get current positions
int current_pos[SERVO_COUNT];
      for (int i = 0; i < SERVO_COUNT; i++) {
        if (servo_pins_[i] != -1) {
          current_pos[i] = servo_[i].GetPosition();
        } else {
          current_pos[i] = LEG_HOME_POSITION;
        }
      }


  current_pos[LEFT_FRONT_LEG] = 0;  // servo1
  current_pos[RIGHT_REAR_LEG] = 0;    // servo3
  current_pos[LEFT_REAR_LEG] = 180;     // servo2
  current_pos[RIGHT_FRONT_LEG] = 180; // servo4
  MoveServos(100, current_pos);
}

void EDARobotDog::Shake(int period) {
  // Shake: rock the body side to side; left-front and right-rear legs move in opposite directions
  int A[SERVO_COUNT] = {20, 0, 20, 0}; // Only the front legs shake
  int O[SERVO_COUNT] = {0, LEG_HOME_POSITION, 0, LEG_HOME_POSITION};
  // Left-front and right-front legs shake out of phase
  double phase_diff[SERVO_COUNT] = {DEG2RAD(180), 0, DEG2RAD(0), 0};

  Execute(A, O, period, phase_diff, 3);
}

void EDARobotDog::EnableServoLimit(int diff_limit) {
  for (int i = 0; i < SERVO_COUNT; i++) {
    if (servo_pins_[i] != -1) {
      servo_[i].SetLimiter(diff_limit);
    }
  }
}

void EDARobotDog::DisableServoLimit() {
  for (int i = 0; i < SERVO_COUNT; i++) {
    if (servo_pins_[i] != -1) {
      servo_[i].DisableLimiter();
    }
  }
}

void EDARobotDog::Sleep() {

  int current_pos[SERVO_COUNT];
  for (int i = 0; i < SERVO_COUNT; i++) {
    if (servo_pins_[i] != -1) {
      current_pos[i] = servo_[i].GetPosition();
    } else {
      current_pos[i] = LEG_HOME_POSITION;
    }
  }

  // servo1.write(0); servo3.write(180); servo2.write(180); servo4.write(0);
  current_pos[LEFT_FRONT_LEG] = 0;   // servo1
  current_pos[RIGHT_REAR_LEG] = 180; // servo3
  current_pos[LEFT_REAR_LEG] = 180;  // servo2
  current_pos[RIGHT_FRONT_LEG] = 0;  // servo4
  MoveServos(100, current_pos);
}