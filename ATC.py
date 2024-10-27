import paho.mqtt.client as mqtt
import time
import json
import random
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import Status, StatusCode
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter, BatchSpanProcessor
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.resources import Resource


# Set up tracing
servicename = Resource.create({"service.name": "Air Traffic Control"})
provider = TracerProvider(resource=servicename)
trace.set_tracer_provider(provider)

jaeger_exporter = JaegerExporter(
    agent_host_name='localhost',
    agent_port=6831,              # Default port for Thrift over UDP
)

# Configure Console Exporter
console_exporter = ConsoleSpanExporter()

# Add processors for both exporters
provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))
provider.add_span_processor(SimpleSpanProcessor(console_exporter))

# Create a tracer
tracer = trace.get_tracer(__name__)


broker = "test.mosquitto.org"
publish_topic = "system/AirTrafficControl/Instructions"

client = mqtt.Client()
client.connect(broker)

# Global counter variable
counter = 0


def publish_message(message_code, codetype, message, qos):
    global counter  # Use the global counter variable
    with tracer.start_as_current_span("Publish message from AirTrafficControl!") as span:
        trace_id = format(span.get_span_context().trace_id, '032x')  # Convert trace_id to hex string
        span_id = format(span.get_span_context().span_id, '016x')  # Convert span_id to hex string
        # Increment the counter for each message published
        counter += 1
        message_size = len(message) + len(codetype)
        timestamp = int(time.time() * 1000)

        payload = json.dumps(
            {"message_code": message_code,
             "codetype": codetype,
             "message": message,
             "timestamp": timestamp,
             "trace_id": trace_id,
             "span_id": span_id,
             "counter": counter}
        )
        span.set_attribute("message.timestamp", timestamp)
        span.set_attribute("message.content", message)
        span.set_attribute("message.code", message_code)
        span.set_attribute("message.codetype", codetype)
        span.set_attribute("message.counter", counter)
        span.set_attribute("message.size", message_size)
        span.set_attribute("mqtt.broker", broker)
        span.set_attribute("mqtt.topic", publish_topic)
        result = client.publish(publish_topic, payload, qos=qos)

        span.set_attribute("mqtt.publish.result", result.rc)

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            span.set_status(StatusCode.OK)
        else:
            span.set_status(StatusCode.ERROR)

    print(f"Published message - Code: {message_code}, Type: {codetype}, Message: {message}, Counter: {counter}")


try:
    # Define a list of possible messages as tuples with (code, codetype, message_content)
    possible_messages = [
        (1, "WARNING", "DANGER! Air traffic is dense around the airport! Watch out for other planes to avoid collision!"),
        (2, "INFORMATION", "STATUS: Weather conditions are stable. Smooth landing expected."),
        (3, "INSTRUCTION", "EMERGENCY! Unexpected turbulence ahead, take immediate precautions!"),
        (4, "ERROR", "SYSTEM FAILURE! Something went wrong, communications are down!")
    ]

    while True:
        # Randomly select one message tuple (code, codetype, message_content) from the list
        message_code, codetype, message_content = random.choice(possible_messages)

        # Quality of service level
        qos = 1

        # Publish the message with the selected code, codetype, and concrete message
        publish_message(message_code, codetype, message_content, qos)

        # Wait before sending another one
        time.sleep(3)

except KeyboardInterrupt:
    print("Publishing stopped by user.")
finally:
    client.disconnect()
