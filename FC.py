import paho.mqtt.client as mqtt
import time
import json
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.trace import StatusCode, SpanContext
from opentelemetry.sdk.resources import Resource

# Set up tracing
servicename = Resource.create({"service.name": "Flight Crew"})
provider = TracerProvider(resource=servicename)
trace.set_tracer_provider(provider)

# Configure Jaeger Exporter
jaeger_exporter = JaegerExporter(
    agent_host_name='localhost',
    agent_port=6831,              # Default port for Jaeger agent in Thrift
)

# Configure Console Exporter
console_exporter = ConsoleSpanExporter()

# Use BatchSpanProcessor for Jaeger and SimpleSpanProcessor for Console
provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))
provider.add_span_processor(SimpleSpanProcessor(console_exporter))

tracer = trace.get_tracer(__name__)

broker = "test.mosquitto.org"
subscribe_topic = "system/AirTrafficControl/Instructions"
publish_topic1 = "system/FlightCrew/Instructions/messageToAutomation"
publish_topic2 = "system/FlightCrew/Instructions/messageToProcesses"



automation_online = False

client = mqtt.Client()
client.connect(broker)

def on_status_message(client, userdata, message):
    global automation_online
    status = message.payload.decode()
    if status == "online":
        automation_online = True
        print("Aircraft Automation is online.")
    elif status == "offline":
        automation_online = False
        print("Aircraft Automation is offline.")

client.subscribe("system/AircraftAutomation/Status", qos=1)
client.message_callback_add("system/AircraftAutomation/Status", on_status_message)

def publish_message(message_code, codetype, message, qos):
    with tracer.start_as_current_span("Publish message from Flight Crew!") as span:
        trace_id = format(span.get_span_context().trace_id, '032x')
        span_id = span.get_span_context().span_id
        message_size = len(message) + len(codetype)
        span.set_attribute("message.size", message_size)
        span.set_attribute("mqtt.broker", broker)

        timestamp = int(time.time() * 1000)
        payload = json.dumps({
            "message_code": message_code,
            "codetype": codetype,
            "message": message,
            "timestamp": timestamp,
            "trace_id": trace_id,
            "span_id": format(span_id, '016x')
        })
        span.set_attribute("message.content", message)
        span.set_attribute("message.timestamp", timestamp)

        # Check if Aircraft Automation is online
        if automation_online:
            print(f"Aircraft Automation is online. Sending to Automation...")
            # First attempt: Send to Aircraft Automation (publish_topic1)
            result1 = client.publish(publish_topic1, payload, qos=qos)
            span.set_attribute("mqtt.topic", publish_topic1)
            span.set_attribute("mqtt.publish.result_topic1", result1.rc)

            if result1.rc == mqtt.MQTT_ERR_SUCCESS:
                span.set_status(StatusCode.OK)
                print(f"Message sent to Aircraft Automation (Topic: {publish_topic1})")
            else:
                print(f"Failed to send to Aircraft Automation. Sending to Processes instead...")
                result2 = client.publish(publish_topic2, payload, qos=qos)
                span.set_attribute("mqtt.topic", publish_topic2)
                span.set_attribute("mqtt.publish.result_topic2", result2.rc)
        else:
            # Aircraft Automation is offline, send directly to Processes
            print(f"Aircraft Automation is offline. Sending to Processes...")
            result2 = client.publish(publish_topic2, payload, qos=qos)
            span.set_attribute("mqtt.topic", publish_topic2)
            span.set_attribute("mqtt.publish.result_topic2", result2.rc)

            if result2.rc == mqtt.MQTT_ERR_SUCCESS:
                span.set_status(StatusCode.OK)
                print(f"Message sent to Processes (Topic: {publish_topic2})")
            else:
                span.set_status(StatusCode.ERROR)
                print(f"Failed to send to Processes.")

def on_message(client, userdata, message):
    payload = json.loads(message.payload.decode())
    trace_id = int(payload.get("trace_id"), 16)
    span_id = int(payload.get("span_id"), 16)

    # Create a new SpanContext using the trace_id and span_id
    context = trace.set_span_in_context(
        trace.NonRecordingSpan(
            SpanContext(
                trace_id=trace_id,
                span_id=span_id,
                is_remote=True,
                trace_flags=trace.TraceFlags(1),
                trace_state=trace.TraceState(),
            )
        )
    )

    with tracer.start_as_current_span("Flight Crew received the message!", context=context) as span:
        received_timestamp = int(time.time() * 1000)
        published_timestamp = payload.get("timestamp")
        message_content = payload.get("message")
        message_code = payload.get("message_code")
        codetype = payload.get("codetype")

        span.set_attribute("message.received_timestamp", received_timestamp)
        span.set_attribute("message.published_timestamp", published_timestamp)
        span.set_attribute("mqtt.topic", message.topic)
        span.set_attribute("message.code", message_code)
        span.set_attribute("message.codetype", codetype)
        span.set_attribute("message.content", message_content)

        print(f"Received message - Code: {message_code}, Type: {codetype}, Content: {message_content}")

        # Message transformation logic
        if message_code == 1 and codetype == "WARNING":
            transformed_message_1 = "Lower engine performance!"
            transformed_message_2 = "Adjust speed!"
            publish_message(11, "INSTRUCTION", transformed_message_1, qos=1)
            publish_message(12, "INSTRUCTION", transformed_message_2, qos=1)

        elif message_code == 2 and codetype == "INFORMATION":
            transformed_message = "Check system information!"
            publish_message(21, "NO OPERATION", transformed_message, qos=1)

        elif message_code == 3 and codetype == "INSTRUCTION":
            transformed_message = "Engage autopilot mode!"
            publish_message(31, "INSTRUCTION", transformed_message, qos=1)

        elif message_code == 4 and codetype == "ERROR":
            transformed_message = "Switch to manual control!"
            publish_message(41, "INSTRUCTION", transformed_message, qos=1)

        else:
            # Forward the message unchanged if no transformation is required
            publish_message(message_code, codetype, message_content, qos=1)

client.on_message = on_message
client.subscribe(subscribe_topic, qos=1)

client.loop_forever()
