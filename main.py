import argparse
from WeatherService import WeatherService

def main():
    parser = argparse.ArgumentParser(
        description="Stormwatch US Weather Alert Monitor"
    )

    parser.add_argument(
        "--test-tornado",
        action="store_true",
        help="Play a mock tornado warning to test alert.mp3",
    )
    parser.add_argument(
        "--test-hurricane",
        action="store_true",
        help="Play a mock hurricane warning to test alert.mp3",
    )

    args = parser.parse_args()

    weather_service = WeatherService(interval=60)

    if args.test_tornado or args.test_hurricane:
        if args.test_hurricane:
            event = "Hurricane Warning"
            alert_id = "MOCK-HURRICANE-WARNING-001"
        else:
            event = "Tornado Warning"
            alert_id = "MOCK-TORNADO-WARNING-001"

        mock_alert = {
            "id": alert_id,
            "event": event,
            "headline": f"TEST ALERT: Mock {event}",
            "area": "TEST AREA - No real weather threat",
            "severity": "Extreme",
            "urgency": "Immediate",
            "sent": "TEST",
            "expires": "TEST",
            "instruction": (
                "This is a software test. "
                "No actual weather warning has been issued."
            ),
            "url": "https://www.weather.gov/",
        }

        print(f"\\n*** MOCK {event.upper()} TEST ***")
        print("This is not a real weather alert.\\n")

        try:
            weather_service.notify(mock_alert)
        finally:
            weather_service.session.close()
        return

    weather_service.run_forever()


if __name__ == "__main__":
    main()