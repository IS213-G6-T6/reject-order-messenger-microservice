from flask import Flask, request, jsonify
from flask_cors import CORS
from twilio.rest import Client
import amqp_setup
import json
import pika

import os, sys

import requests
from invokes import invoke_http

app = Flask(__name__)
CORS(app)


account_sid = 'AC3983540c484253b5bd88c59a6c909889'
auth_token = 'a26344cea222e020b47b1b829ba77415'
twilio_phone_number = '+14406933814'
receipient = '+33756491209'

client = Client(account_sid, auth_token)

order_URL = "http://host.docker.internal:5000/order"
payment_URL = "http://host.docker.internal:5001/payment"
activity_log_URL = "http://host.docker.internal:5002/activity_log"
error_URL = "http://host.docker.internal:5003/error"


@app.route("/reject_order", methods=['POST'])
def reject_order():
    # Simple check of input format and data of the request are JSON
    if request.is_json:
        try:
            order = request.get_json()
            print("\nRetrieved an order in JSON:", order)

            # do the actual work
            # 1. Send Rejected order info {cart items}
            result = processRejectOrder(order)
            return jsonify(result), result["code"]

        except Exception as e:
            # Unexpected error in code
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            ex_str = str(e) + " at " + str(exc_type) + ": " + fname + ": line " + str(exc_tb.tb_lineno)
            print(ex_str)
            amqp_setup.channel.basic_publish(exchange=amqp_setup.exchangename, routing_key="reject.error", body=json.dumps(ex_str), properties=pika.BasicProperties(delivery_mode = 2))
            return jsonify({
                "code": 500,
                "message": "reject_order.py internal error: " + ex_str
            }), 500

    # if reached here, not a JSON request.
    amqp_setup.channel.basic_publish(exchange=amqp_setup.exchangename, routing_key="reject.error", body=json.dumps("Invalid JSON input: " + str(request.get_data())), properties=pika.BasicProperties(delivery_mode = 2))
    return jsonify({
        "code": 400,
        "message": "Invalid JSON input: " + str(request.get_data())
    }), 400


def processRejectOrder(order):
    orderID = order["orderID"]
    # Retrieve the order details
    print('\n-----Invoking order microservice-----')
    order_status = invoke_http(order_URL + "/" + orderID, method="PUT", json={"status": "reject order"})
    print('order_status:', order_status)
    
    # 4. Record rejected order
    # record the activity log anyway
    # print('\n\n-----Invoking activity_log microservice-----')
    # invoke_http(activity_log_URL, method="POST", json=order_status)
    # print("\nRejected Order sent to activity log.\n")

    # - reply from the invocation is not used;
    # continue even if this invocation fails
    # Check the order status; if a failure, send it to the error microservice.
    code = order_status["code"]
    if code not in range(200, 300):

    # Inform the error microservice
        print('\n\n-----Invoking error microservice as order fails-----')
        # - reply from the invocation is not used; 
        # continue even if this invocation fails
        print("Order status ({:d}) sent to the error microservice:".format(
            code), order_status)
        amqp_setup.channel.basic_publish(exchange=amqp_setup.exchangename, routing_key="rejectupdateorder.error", body=json.dumps({"message": "Order rejection failure sent for error handling."}), properties=pika.BasicProperties(delivery_mode = 2))
    # 7. Return error
        return {
            "code": 500,
            "data": {"order_status": order_status},
            "message": "Order rejection failure sent for error handling."
        }
    
    # 5. Send notification to payment microservice
    # Invoke the payment microservice for refund
    print('\n\n-----Invoking payment microservice-----')
    refund_result= invoke_http(payment_URL + "/refund/" + orderID, method="GET")

    print("payment_result:", refund_result, '\n')
    # Check the shipping result;
    # if a failure, send it to the error microservice.
    code = refund_result["code"]
    if code not in range(200, 300):
        amqp_setup.channel.basic_publish(exchange=amqp_setup.exchangename, routing_key="rejectrefund.error", body=json.dumps({"message": "Refund error sent for error handling."}), properties=pika.BasicProperties(delivery_mode = 2))
    # Inform the error microservice
        print('\n\n-----Invoking error microservice as refund fails-----')
        invoke_http(error_URL, method="POST", json=refund_result)
        print("Shipping status ({:d}) sent to the error microservice:".format(
            code), refund_result)


    # 7. Return error
        return {
            "code": 500,
            "data": {
                "refund_result": refund_result
            },
            "message": "Refund error sent for error handling."
        }

    # 7. Return created order, shipping record
    order_refund_status = invoke_http(order_URL + "/" + orderID, method="PUT", json={"status": "reject order, payment refunded"})
    code = order_refund_status["code"]
    if code not in range(200, 300):
        amqp_setup.channel.basic_publish(exchange=amqp_setup.exchangename, routing_key="updaterefundedorder.error", body=json.dumps({"message": "update order Refunded error sent for error handling."}), properties=pika.BasicProperties(delivery_mode = 2))
    # Inform the error microservice
        print('\n\n-----Invoking error microservice as refund fails-----')
        invoke_http(error_URL, method="POST", json=order_refund_status)
        print("Shipping status ({:d}) sent to the error microservice:".format(
            code), order_refund_status)

    # 7. Return error
        return {
            "code": 500,
            "data": {
                "order_refunded_update_result": order_refund_status
            },
            "message": "order Refunded update error sent for error handling."
        }
    
    # Send TWILIO SMS notification
    message = client.messages.create(
        body="Order Rejected",
        from_ = twilio_phone_number,
        to = receipient
    )
    print("SMS notification sent: ", message.sid)
    print(message)
    
    # if message["code"]:
    #     code = message["code"]
    #     if code not in range(200, 300):
    #         # Inform the error microservice
    #         amqp_setup.channel.basic_publish(exchange=amqp_setup.exchangename, routing_key="twilio.error", body=json.dumps({"code": 500, "message": "error when sending to twilio"}), properties=pika.BasicProperties(delivery_mode = 2))
    #     # 7. Return error
    #         return {
    #             "code": 400,
    #             "data": {
    #                 "order_refunded_update_result": message
    #             },
    #             "message": "order Refunded update error sent for error handling."
    #         }
    amqp_setup.channel.basic_publish(exchange=amqp_setup.exchangename, routing_key="twilio.success", body=json.dumps({"code": 200, "message": "twilio successfully send"}), properties=pika.BasicProperties(delivery_mode = 2))
    amqp_setup.channel.basic_publish(exchange=amqp_setup.exchangename, routing_key="reject.success", body=json.dumps({"order_status": order_status, "refund_result": refund_result, "order_refunded_update_result": order_refund_status}), properties=pika.BasicProperties(delivery_mode = 2))
    return {
        "code": 201,
        "data": {
            "order_status": order_status,
            "refund_result": refund_result,
            "order_refunded_update_result": order_refund_status
        }
    }

# Execute this program if it is run as a main script (not by 'import')
if __name__ == "__main__":
    print("This is flask " + os.path.basename(__file__) +
          " for placing an order...")
    app.run(host="0.0.0.0", port=5101, debug=True)
    # Notes for the parameters:
    # - debug=True will reload the program automatically if a change is detected;
    #   -- it in fact starts two instances of the same flask program,
    #       and uses one of the instances to monitor the program changes;
    # - host="0.0.0.0" allows the flask program to accept requests sent from any IP/host (in addition to localhost),
    #   -- i.e., it gives permissions to hosts with any IP to access the flask program,
    #   -- as long as the hosts can already reach the machine running the flask program along the network;
    #   -- it doesn't mean to use http://0.0.0.0 to access the flask program.