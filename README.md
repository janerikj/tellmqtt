# tellmqtt

This program acts as a bridge between a USB-connected tellstick and 
a mqtt-server, written with python3.

Currently only the Telldus Tellstick Duo is supported.

The MQTT interface is rather raw, incoming data is decoded and published
under `tellstick/in/<protocolname>/<protocoldetails>` while for sending 
data out post a message to `tellstick/out/<protocolname>/<details>` 

## Usage
### Hardware setup
This program needs the tellstick to show up as an ordinary serial port.
This is done with the linux kernel module `ftdi_sio`. However the 
module does not recognize the tellstick out of the box, so some special 
commands are needed (as root):
```
# modprobe ftdi_sio
# echo 1781 0c31 > /sys/bus/usb-serial/drivers/ftdi_sio/new_id
```
After this the kernel log should show something like
```
usbcore: registered new interface driver ftdi_sio
usbserial: USB Serial support registered for FTDI USB Serial Device
ftdi_sio 2-2:1.0: FTDI USB Serial Device converter detected
usb 2-2: Detected FT232RL
usb 2-2: FTDI USB Serial Device converter now attached to ttyUSB0
```

The final `ttyUSB0` shows which device file under `/dev/` was created.

The docs-directory contains a udev rule file (`90-tellstick.rules`) 
which can be used to do this automatically, it also creates a symlink
`/dev/tellstickDuo` to the device and sets permissions so the `plugdev` group
can use it.

### Software setup
I recommend using a python virtual environment, with at least python 3.6:
```
$ cd <tellmqtt main directory>
$ python3 -m venv venv
$ . venv/bin/activate
$ pip install -r requirements.txt
```

### Running tellmqtt
Using the previously created device symlink and virtual environment 
tellmqtt can be started with:
```
$ cd <tellmqtt main directory>
$ . venv/bin/activate
$ python3 -m tellmqtt -d /dev/tellstickDuo -h mqtt-server
```

**NB!** Please do not run tellmqtt as root!

### Tellstick connection
The tellstick has to be present when tellmqtt starts, otherwise tellmqtt
exits with an error.

If the tellstick is unplugged while tellmqtt is running, tellmqtt keeps
running and tries to reopen the device every 5 seconds. The first attempt
is logged as a warning, further attempts as debug messages, and a message is
logged when the tellstick is back. Note that commands received from mqtt
while the tellstick is gone are dropped.

### Environment variables
Some settings can be set using environment variables. If a command
line option exists, it takes precedence.

| Variable | Meaning | Default |
|---|---|---|
| `TELLMQTT_HOST` | MQTT broker host | `localhost` |
| `TELLMQTT_PORT` | MQTT broker port | `1883` |
| `TELLMQTT_USER` | MQTT username | unset |
| `TELLMQTT_PASSWORD` | MQTT password | unset |
| `TELLMQTT_LOG_LEVEL` | Log level, e.g. `DEBUG` | `INFO` |
| `TELLMQTT_OREGON_CHECKSUM` | Validate the Oregon checksum so a THGN132N sensor is reported under its model name `1D20`. Enabled when set to a truthy value (`1`, `true`, `yes`, `on`). When unset, other Oregon models may work but may be labeled `1A2D` by the Tellstick. | unset (off) |
| `TELLMQTT_DEDUP_WINDOW_MS` | Suppress repeated identical decoded output arriving within this time window (in milliseconds), e.g. `500`. Sensors often repeat a transmission; only the first identical result within the window is published. `0` or unset disables the filter. | unset (off) |
| `TELLMQTT_FINEOFFSET_CHANNEL_IN_TOPIC` | Add the channel and probe levels to the fineoffset topic, see [Fineoffset](#fineoffset). Enabled when set to a truthy value (`1`, `true`, `yes`, `on`). | unset (off) |

Example:
```
$ TELLMQTT_HOST=192.168.1.5 TELLMQTT_OREGON_CHECKSUM=true python3 -m tellmqtt -d /dev/tellstickDuo
```

## Tested devices (protocols)
Where a protocol has a channel, it comes first in the topic, followed by the
level identifying the sensor: the model (oregon), the probe (fineoffset) or
the house (mandolyn). Arctech and waveman have no channel and use house and
unit.

### Fineoffset
#### Telldus Thermo- and hygrometer
Models FT007TH, F007TPH

The following topics are published:

`tellstick/in/fineoffset/<id>/temperature` temperature

`tellstick/in/fineoffset/<id>/humidity` humidity (if applicable)

`tellstick/in/fineoffset/<id>/json` all data in a json structure (useful if logging to database)

The termo-/hygrometers have dipswitches to set the channel 1-8. The id they
report holds the channel + 7 in its high nibble and the probe in its low
nibble, 7 for the internal and 8 for the external one, so the ids of the two
probes interleave, from 135/136 on channel 1 to 247/248 on channel 8. For the
combined sensor (F007TPH) the external temperature is a separate sensor
reporting its own id on the same channel, and it has no humidity.

So `<id>` is not the channel the sensor is set to. The ids we have seen are
151/152 (channel 2), 231 (channel 7, internal) and 247/248 (channel 8).

#### Channel and probe levels in the topic
The topics above have one level too few, and that level is an id rather than
the channel. With `TELLMQTT_FINEOFFSET_CHANNEL_IN_TOPIC` set, the channel and
probe levels are added:

`tellstick/in/fineoffset/<channel>/<probe>/temperature` temperature

`tellstick/in/fineoffset/<channel>/<probe>/humidity` humidity (internal only)

`tellstick/in/fineoffset/<channel>/<probe>/json` all data in a json structure

`<probe>` is `intern` or `extern`. Both levels are needed, since the probes
of an F007TPH report different ids on the same channel. The internal probe on
channel 8 is published as `tellstick/in/fineoffset/8/intern/temperature` and
its external probe as `tellstick/in/fineoffset/8/extern/temperature`.

An id that is not one of those listed above, so not a channel 1-8 sensor, is
published as the only level as before, and logged as a warning.

Note that enabling this changes the topics, so any subscriber has to be
updated.

### Arctech 
#### Arctech self-learning
The arctech self-learning protocol reads/writes to 
`tellstick/(in/out)/arctech/selflearning/<house>/<group>/<unit>/set`

where

`<house>` is a number 0 - 67108863

`<group>` is 0 or 1

`<unit>` is 1 - 16

The value of the topic on input can be either `on` or `off` (case insensitive).
On output also the value `learn` can be given to learn a new code (provided that the receiver is in learning mode)

#### Arctech Codeswitch

The Arctech codeswitch model reads/writes to 
`tellstick/(in/out)/arctech/selflearning/<house>/<unit>/set`

where

`<house>` is a number 0 - 15 (corresponding to ones encoded by letters A-...)

`<unit>` is 0 - 15

The value of the topic on input can be either `on` or `off` (case insensitive).

#### Telldus remote control
Model EWT0006

The remote has 4 on/off buttons: 1, 2, 3 and G

The house-code is hardcoded per device. To find it out use 
`mosquitto_sub -v -t tellstick/in/\#` and press the buttons (or use another mqtt subscriber)

Then group/unit is used as:

1: 0/16

2: 0/15

3: 0/14

G: 1/16

#### Nexa doorbell button
This works a lot like the Telldus remote control, but it only send an `ON` signal
with group = 1, unit = 1.

#### Telldus power-switch
Models EWR1003 and 312538

1. Decide on a valid combination of house, group and unit codes 
2. Set your receiving device in learning mode
3. send `LEARN` to `/tellstick/out/arctech/selflearning/<house>/<group>/<unit>/set`

Then send `ON`/`OFF` to `/tellstick/out/arctech/selflearning/<house>/<group>/<unit>/set`
to turn the switch on/off.

#### Nexa doorbell
Follow the telldus power-switch instructions. Note that the doorbell only listens to the `LEARN` and `ON`
commands.

### Mandolyn
#### Thermo- and hygrometer
Models ESIC WT450H

The following topics are published:

`tellstick/in/mandolyn/<channel>/<house>/temperature` temperature

`tellstick/in/mandolyn/<channel>/<house>/humidity` humidity

`tellstick/in/mandolyn/<channel>/<house>/battery` battery (0 = ok, 1 = low)

`tellstick/in/mandolyn/<channel>/<house>/json` all data in a json structure (useful if logging to database)

The termo-/hygrometers have dipswitches to set the channel 1-4 and house 1-15

### Waveman
#### Waveman Codeswitch

The Waveman codeswitch model reads/writes to 
`tellstick/(in/out)/waveman/codeswitch/<house>/<unit>/set`

where

`<house>` is a letter 'a' - 'p' (case insensitive)

`<unit>` is 1 - 16

The value of the topic on input can be either `on` or `off` (case insensitive).

### Oregon
#### Thermo- and hygrometer
Model THGN132N 

The following topics are published:

`tellstick/in/oregon/<channel>/<model>/temperature` temperature

`tellstick/in/oregon/<channel>/<model>/humidity` humidity

`tellstick/in/oregon/<channel>/<model>/battery` battery (0 = ok, 1 = low)

`tellstick/in/oregon/<channel>/<model>/json` all data in a json structure (useful if logging to database)

The checksum check is controlled by the `TELLMQTT_OREGON_CHECKSUM`
environment variable, see [Environment variables](#environment-variables).


## HomeAssistant examples
Here are examples on how to use tellmqtt with HomeAssistant and its mqtt-support.
### Internal/external temperature/humidity sensor
Sensor with ID set to 2, meaning the internal probe reports 151 and the
external one 152. The topics assume that
`TELLMQTT_FINEOFFSET_CHANNEL_IN_TOPIC` is not set, see
[Fineoffset](#fineoffset). With it set, the topics are
`tellstick/in/fineoffset/2/intern/temperature`,
`tellstick/in/fineoffset/2/intern/humidity` and
`tellstick/in/fineoffset/2/extern/temperature`.
```yaml
sensor:
  - platform: mqtt
    state_topic: "tellstick/in/fineoffset/151/temperature"
    name: "Internal temperature"
    device_class: "temperature"
    unit_of_measurement: '°C'
  - platform: mqtt
    state_topic: "tellstick/in/fineoffset/151/humidity"
    name: "Internal humidity"
    device_class: "humidity"
    unit_of_measurement: '%'
  - platform: mqtt
    state_topic: "tellstick/in/fineoffset/152/temperature"
    name: "External temperature"
    device_class: "temperature"
    unit_of_measurement: '°C'
```

### Telldus remote control
```yaml
binary_sensor:
  - platform: mqtt
    state_topic: "tellstick/in/arctech/selflearning/123/0/16/set"
    name: "Remote 1"
  - platform: mqtt
    state_topic: "tellstick/in/arctech/selflearning/123/0/15/set"
    name: "Remote 2"
  - platform: mqtt
    state_topic: "tellstick/in/arctech/selflearning/123/0/14/set"
    name: "Remote 3"
  - platform: mqtt
    state_topic: "tellstick/in/arctech/selflearning/123/1/16/set"
    name: "Remote G"

```
Replace `123` with the house code of your remote control.

### Power switch
```yaml
switch:
  - platform: mqtt
    command_topic: "tellstick/out/arctech/selflearning/456/0/1/set"
    name: "Powerswitch"
```
Replace `456/0/1` with the house, group and unit codes of your switch

TellStick is a trademark of Telldus Technologies AB
