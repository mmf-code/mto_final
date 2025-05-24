import spidev
import time
import datetime
from influxdb import InfluxDBClient
import argparse

# Argümanları alma
parser = argparse.ArgumentParser(description='Anemometer Test')
parser.add_argument('--speed', type=int, required=True, help='Test edilen rüzgar hızı (m/s)')
args = parser.parse_args()

# Test edilen rüzgar hızı
current_test_speed = args.speed

# InfluxDB client ayarları
client = InfluxDBClient(host='localhost', port=8086)
client.switch_database('mydatabase')

# SPI ayarları
spi = spidev.SpiDev()
spi.open(0, 0)
spi.max_speed_hz = 1000000

def read_adc(channel):
    adc = spi.xfer2([1, (8 + channel) << 4, 0])
    data = ((adc[1] & 3) << 8) + adc[2]
    return data

baseline = read_adc(0)
last_magnet_pass_time = None
magnet_passed = False
minimum_time_interval = 0.15
conversion_factor = 1

wind_speeds = []
last_second = None
moving_average_window = 5
speed_readings = []
previous_wheel_speed = None
tolerance_factor = 0.35  # Tolerans faktörünü 0.35 olarak ayarladık
drop_tolerance_factor = 0.5  # Anlık düşüş tolerans faktörü

def moving_average(new_value, window_size):
    if len(speed_readings) >= window_size:
        speed_readings.pop(0)
    speed_readings.append(new_value)
    return sum(speed_readings) / len(speed_readings)

def is_outlier(current_value, previous_value, tolerance_factor):
    if previous_value is None:
        return False
    return (current_value < previous_value * (1 - tolerance_factor))

try:
    while True:
        value = read_adc(0)
        current_time = datetime.datetime.now()
        
        # Ham verileri 'wind_raw' measurement'ına kaydet
        raw_data_points = [{
            "measurement": "wind_raw",
            "tags": {
                "test_speed": current_test_speed  # Test edilen rüzgar hızı tag olarak ekleniyor
            },
            "time": current_time.isoformat(),
            "fields": {
                "adc_value": float(value)
            }
        }]
        client.write_points(raw_data_points)

        # Yeni bir saniye kontrolü
        if last_second is None or current_time.second != last_second:
            if wind_speeds:  # Önceki saniyenin verilerini kaydet
                average_wind_speed = sum(wind_speeds) / len(wind_speeds)
                
                # Sapmayı hesapla
                deviation = ((average_wind_speed - current_test_speed) / current_test_speed) * 100

                # Yeni conversion factor hesapla
                new_conversion_factor = current_test_speed / (average_wind_speed / conversion_factor) if average_wind_speed > 0 else conversion_factor
                
                wind_data_points = [{
                    "measurement": "wind",
                    "tags": {
                        "location": "example_location",
                        "test_speed": current_test_speed  # Test edilen rüzgar hızı tag olarak ekleniyor
                    },
                    "time": current_time.replace(microsecond=0).isoformat(),
                    "fields": {
                        "average_wind_speed": average_wind_speed,
                        "deviation": deviation,
                        "new_conversion_factor": new_conversion_factor
                    }
                }]
                client.write_points(wind_data_points)
                print(f"Average Wind Speed for second {last_second}: {average_wind_speed:.3f} m/s, Deviation: {deviation:.2f}%, New Conversion Factor: {new_conversion_factor:.3f}")
                
                wind_speeds = []

            last_second = current_time.second

        current_magnet_state = value > baseline + 50
        if current_magnet_state:
            if not magnet_passed:
                if last_magnet_pass_time:
                    time_diff = (current_time - last_magnet_pass_time).total_seconds()
                    if time_diff > minimum_time_interval:
                        wheel_circumference = 2 * 0.03 * 3.14159
                        wheel_speed = wheel_circumference / time_diff if time_diff > 0 else 0

                        # Anlık düşüş kontrolü
                        if previous_wheel_speed is None or not is_outlier(wheel_speed, previous_wheel_speed, drop_tolerance_factor):
                            previous_wheel_speed = wheel_speed
                            wind_speed = wheel_speed * conversion_factor
                            filtered_wind_speed = moving_average(wind_speed, moving_average_window)
                            wind_speeds.append(filtered_wind_speed)

                            # Anlık hız hesaplamalarını yazdır
                            print(f"Wheel Speed: {wheel_speed:.3f} m/s, Wind Speed (converted): {wind_speed:.3f} m/s, Time Interval: {time_diff:.3f} seconds")
                            
                            # İnfluxDB'ye veri yaz
                            points = [{
                                "measurement": "weather",
                                "tags": {
                                    "location": "example_location",
                                    "test_speed": current_test_speed  # Test edilen rüzgar hızı tag olarak ekleniyor
                                },
                                "time": current_time.isoformat(),
                                "fields": {
                                    "wheel_speed": float(wheel_speed),
                                    "wind_speed": float(wind_speed),
                                    "time_interval": float(time_diff)
                                }
                            }]
                            client.write_points(points)
                        
                last_magnet_pass_time = current_time
                magnet_passed = True
        else:
            magnet_passed = False
        
        time.sleep(0.001)

except KeyboardInterrupt:
    spi.close()

    # Program sonlandığında kalan verileri kaydet
    if wind_speeds:
        average_wind_speed = sum(wind_speeds) / len(wind_speeds)
        
        # Sapmayı hesapla
        deviation = ((average_wind_speed - current_test_speed) / current_test_speed) * 100

        # Yeni conversion factor hesapla
        new_conversion_factor = current_test_speed / (average_wind_speed / conversion_factor) if average_wind_speed > 0 else conversion_factor
        
        wind_data_points = [{
            "measurement": "wind",
            "tags": {
                "location": "example_location",
                "test_speed": current_test_speed  # Test edilen rüzgar hızı tag olarak ekleniyor
            },
            "time": datetime.datetime.now().replace(microsecond=0).isoformat(),
            "fields": {
                "average_wind_speed": average_wind_speed,
                "deviation": deviation,
                "new_conversion_factor": new_conversion_factor
            }
        }]
        client.write_points(wind_data_points)
        print(f"Average Wind Speed for last recorded second {last_second}: {average_wind_speed:.3f} m/s, Deviation: {deviation:.2f}%, New Conversion Factor: {new_conversion_factor:.3f}")
