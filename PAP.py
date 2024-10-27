import paho.mqtt.client as mqtt
import time
import json
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter, BatchSpanProcessor
from opentelemetry.trace import StatusCode, SpanContext
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.resources import Resource


# Set up tracing
servicename = Resource.create({"service.name": "Physical Aircraft Processes"})
provider = TracerProvider(resource=servicename)
trace.set_tracer_provider(provider)

jaeger_exporter = JaegerExporter(
    agent_host_name='localhost',  # Change this to your Jaeger agent host
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
subscribe_topic1 = "system/FlightCrew/Instructions/messageToProcesses"
subscribe_topic2 = "system/AircraftAutomation/Instructions/messageToProcesses"

client = mqtt.Client()
client.connect(broker)


def on_message(client, userdata, message):
    # Decode the received message payload
    payload = json.loads(message.payload.decode())

    # Extract trace_id from the payload (assumed to be in hexadecimal string format)
    trace_id_hex = payload.get("trace_id")

    # Convert the trace_id from hexadecimal to an integer
    trace_id = int(payload.get("trace_id"), 16)
    span_id = int(payload.get("span_id"), 16)
    # Extract the message content and other relevant information
    published_timestamp = payload.get("timestamp")
    received_timestamp = int(time.time() * 1000)

    # Create a new SpanContext with the extracted trace_id
    context = trace.set_span_in_context(
        trace.NonRecordingSpan(
            SpanContext(
                trace_id=trace_id,
                span_id=span_id,
                is_remote=True,
                trace_flags=trace.TraceFlags(1),  # Set trace flags (e.g., sampled)
                trace_state=trace.TraceState(),
            )
        )
    )

    # Start a new span using the same trace_id to maintain context

    with tracer.start_as_current_span("Physical Aircraft Processes received the final message!", context=context) as span:
        message_code = payload.get("message_code")
        codetype = payload.get("codetype")
        message_content = payload.get("message")

        span.set_attribute("message.received_timestamp", received_timestamp)
        span.set_attribute("message.published_timestamp", published_timestamp)
        span.set_attribute("mqtt.topic", message.topic)
        span.set_attribute("message.code", message_code)
        span.set_attribute("message.codetype", codetype)
        span.set_attribute("message.content", message_content)

        # Log the received message
        print(f"Received final message - Code: {message_code}, Type: {codetype}, Content: {message_content}")

        # Handle codes from both Flight Crew and Automation
        if (message_code == 11 or message_code == 111) and (codetype == "INSTRUCTION" or codetype == "AUTOMATION"):
            print("Process: Adjusting engine performance...")

        elif (message_code == 12 or message_code == 211) and (codetype == "INSTRUCTION" or codetype == "AUTOMATION"):
            print("Process: Adjusting aircraft speed...")

        elif (message_code == 31 or message_code == 311) and (codetype == "INSTRUCTION" or codetype == "AUTOMATION"):
            print("Process: Engaging autopilot...")

        elif (message_code == 41 or message_code == 411) and (codetype == "INSTRUCTION" or codetype == "AUTOMATION"):
            print("Process: Switching to manual control...")

        else:
            # Log or handle other types of messages
            print(f"Great success! - Code: {message_code}, Type: {codetype}, Content: {message_content}")

client.on_message = on_message
client.subscribe(subscribe_topic1, qos=1)
client.subscribe(subscribe_topic2, qos=1)

client.loop_forever()
