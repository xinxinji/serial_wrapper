# serial_wrapper

Serial Wrapper for those device which support serial control.

Currently, it support below function:
* start
* stop
* close
* write
* send_break
* input_output_blocking
* wait_for_strings
* wait_for_string
* create_logger
* close_logger
* create_serial_monitor
* close_serial_monitor

Example:
```Python
    from serial_wrapper import SerialWrapper
    s = SerialWrapper('COM1')
    serial_log = s.create_logger(r'C:\Log\serial.log')
    s.write('which id\n')
    s.wait_for_string('/system')
    s.close_logger(serial_log)
```