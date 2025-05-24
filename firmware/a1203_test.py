import spidev
import time
import datetime
from influxdb import InfluxDBClient
import argparse
import pandas as pd
import numpy as np
import os
from gpiozero import Button

# Argümanları alma
parser = argparse.ArgumentParser(description='Anemometer Test')
parser.add_argument('--speed', type=int, required=True, help='Test edilen rüzgar hızı (m/s)')
args = parser.parse_args()

# Test edilen rüzgar hızı
current_test_speed = args.speed

# InfluxDB client ayarları
client = InfluxDBClient(host='localhost', port=8086)
try:
    client.switch_database('a1203')
except Exception as e:
    print(f"Veritabanına bağlanırken hata oluştu: {e}")

# GPIO pin numarasını ayarla
sensor = Button(17)

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
minimum_time_interval = 0.15
conversion_factor = 1

# Hareketli Ortalama
wind_speeds = []
last_second = None
moving_average_window = 5
speed_readings = []
previous_wheel_speed = None
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

# Boş DataFrame
data_columns = ['Time', 'Wheel Speed', 'Wind Speed', 'Deviation', 'New Conversion Factor']
data_records = pd.DataFrame(columns=data_columns)

try:
    while True:
        if sensor.is_pressed:
            current_time = time.time()
            if last_magnet_pass_time:
                time_diff = current_time - last_magnet_pass_time
                if time_diff > minimum_time_interval:
                    wheel_circumference = 2 * 0.03 * 3.14159 * 0.66
                    wheel_speed = wheel_circumference / time_diff if time_diff > 0 else 0

                    # Anlık düşüş kontrolü
                    if previous_wheel_speed is None or not is_outlier(wheel_speed, previous_wheel_speed, drop_tolerance_factor):
                        previous_wheel_speed = wheel_speed
                        wind_speed = wheel_speed * conversion_factor
                        print(f"Wheel Speed: {wheel_speed:.3f} m/s, Wind Speed (converted): {wind_speed:.3f} m/s, Time Interval: {time_diff:.3f} seconds")
                        
                        index = len(data_records)
                        data_records.loc[index] = [datetime.datetime.now(), wheel_speed, wind_speed, np.nan, np.nan]

                        points = [{
                            "measurement": "sensor_data",
                            "tags": {
                                "location": "test_location"
                            },
                            "time": datetime.datetime.now().isoformat(),
                            "fields": {
                                "wheel_speed": float(wheel_speed),
                                "wind_speed": float(wind_speed),
                                "time_interval": float(time_diff)
                            }
                        }]
                        if not client.write_points(points):
                            print("Veri yazılırken bir hata oluştu.")
                        
                        filtered_wind_speed = moving_average(wind_speed, moving_average_window)
                        wind_speeds.append(filtered_wind_speed)

            last_magnet_pass_time = current_time

        current_datetime = datetime.datetime.now()
        if last_second is None or current_datetime.second != last_second:
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
                        "test_speed": current_test_speed
                    },
                    "time": current_datetime.replace(microsecond=0).isoformat(),
                    "fields": {
                        "average_wind_speed": average_wind_speed,
                        "deviation": deviation,
                        "new_conversion_factor": new_conversion_factor
                    }
                }]
                client.write_points(wind_data_points)
                print(f"Average Wind Speed for second {last_second}: {average_wind_speed:.3f} m/s, Deviation: {deviation:.2f}%, New Conversion Factor: {new_conversion_factor:.3f}")
                
                wind_speeds = []

                index = len(data_records)
                data_records.loc[index] = [datetime.datetime.now(), np.nan, average_wind_speed, deviation, new_conversion_factor]

            last_second = current_datetime.second

        time.sleep(0.01)

except KeyboardInterrupt:
    spi.close()

    excel_path = '/home/raspberrypi-mmf/Grad/a1203.xlsx'
    if os.path.exists(excel_path):
        existing_data = pd.read_excel(excel_path)
        combined_data = pd.concat([existing_data, data_records])
    else:
        combined_data = data_records
    
    combined_data.to_excel(excel_path, index=False)
    print("Veriler kaydedildi: ", excel_path)

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
                "test_speed": current_test_speed
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
