LIDAR RELAY - on-site steps (Windows laptop next to the projector)
===================================================================
This small program reads the LiDAR and sends it to the game server over the internet. It contains no game.

ONE-TIME SETUP
1. Plug the LiDAR into the laptop with its USB adapter. If Windows does not create a COM port
   (Device Manager > Ports (COM & LPT) shows nothing new), install the "CP210x USB to UART" driver from Silicon Labs.
2. Install Python 3 from python.org (tick "Add python.exe to PATH").
3. Double-click setup.bat (needs internet).
4. Open relay_config.txt in Notepad. Paste the key you were given; set model = S2 or S3. Save.

CHECK THE SENSOR (do this first)
5. Double-click test_connection.bat. After a few seconds the remote engineer should see "relay connected". Close it.
6. Double-click probe.bat. It finds the sensor, spins it for 6 seconds and prints PROBE OK or a problem.
   It also sends the report to the engineer. If it says FAILED/WARNING, send probe_report.txt (and probe_raw.bin) to the engineer.

RUN
7. Double-click run_relay.bat and leave the window open. It reconnects by itself if the internet or the cable drops.
8. In Chrome on the projector computer open the game address given by the engineer (full screen, F11).
   The engineer does the rest (calibration targets appear on the projector).

TROUBLESHOOTING
- "key rejected (HTTP 403)": the key in relay_config.txt is wrong or was regenerated.
- "SERVER SAYS ... not Remote relay": the engineer must choose Source = Remote relay in Admin and press Save.
- "no serial ports found": check the cable / install the CP210x driver.
- Sensor not spinning: check the sensor's power / use a powered USB hub.
- relay.log in this folder keeps a history.
