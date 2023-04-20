from flask import Flask, jsonify, request
from bson.objectid import ObjectId
from flask_cors import CORS
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
from pymongo import MongoClient
from datetime import datetime
from flask_caching import Cache
import redis
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ['SECRET_KEY']

cors = CORS(app)
app.config.from_object(os.environ['APP_SETTINGS'])
MONGO_URI = os.environ.get('MONGO_URI')
cluster = MongoClient(MONGO_URI)
cache = Cache(app, config={'CACHE_TYPE': 'redis', 'CACHE_REDIS_URL': 'redis://localhost:6379/0'})
redis_client = redis.Redis(host='localhost', port=6380, db=0)

mongo_db = cluster['e-commerece-app-db']
products_collection = mongo_db.products
orders_collection = mongo_db.orders
sessions_collection = mongo_db.sessions

def get_product_by_id(id):  
    return products_collection.find_one({"_id": ObjectId(id)})

def get_cached_products():
    products_list = redis_client.get("products")

    if products_list is not None:
        return json.loads(redis_client.get('products').decode('utf-8'))

    return None

def update_cached_products(id, update_data):
    cached_products = get_cached_products()
    if cached_products is None:
        return None
    for cached_product in cached_products:
        if cached_product["id"] == id:
            cached_product.update(update_data)

    redis_client.set("products", json.dumps(cached_products))

def delete_product_from_cache(id):
    cached_products = get_cached_products()
    filtered_products = [product for product in cached_products if product["id"] != id]
    redis_client.set("products", json.dumps(filtered_products))

def find_product_from_cache(attribute,value):
    cached_products = get_cached_products()
    if cached_products is None:
        return None
    for cached_product in cached_products:
        print("Cache hit for products")
        if cached_product[attribute] == value:
            return cached_product
    print("Cache miss for products")
    return None


@app.route("/products", methods=["GET"])
def get_products():
    cached_products = get_cached_products()
    if cached_products is not None:
        return jsonify(cached_products)

    products_list = []
    mongo_products = products_collection.find()

    for item in mongo_products:
        product_dict = {
            "id": str(item['_id']),
            "name"    : str(item['name']),
            "price"   : int(item['price']),
            "in_stock_quantity": int(item['in_stock_quantity'])
        }
        products_list.append(product_dict)
        redis_client.set('products', json.dumps(products_list))

    return jsonify(products_list)


@app.route("/add-to-cart", methods=["POST"])
def add_to_cart():
    try:
        current_user = request.json['current_user']
        item = request.json['item']
        sessions_collection.update_many({'public_id': current_user["email"]}, 
                                        {'$addToSet': { 'items_added': item } })
        return jsonify({"message": "Item added to the cart"}, 200)
        
    except Exception as e:
        print(e)
        return jsonify({"message":"Something went wrong"}),404

@app.route("/checkout", methods=["POST"])
def checkout():
    try:
        current_user = request.json['current_user']
        items = request.json["items"]
        for item in items:
            product = get_product_by_id((item["id"]))
            if int(item["quantity"]) > int(product["in_stock_quantity"]):
                orders_collection.insert_one({
                    "items": items, 
                    "public_id": current_user["email"],
                    "status": "Out of Stock",
                    "order_date": datetime.now()
                })
                return jsonify({
                    "message":f"The item {item['name']} is not available in {item['quantity']} units"
                    }),404
            update_data = {
                "in_stock_quantity": int(product["in_stock_quantity"]) - int(item["quantity"])
            }
            products_collection.update_many({"_id": ObjectId(item["id"])}, 
                                            {"$set": update_data})
            
            orders_collection.insert_one({
                "items": items, 
                "public_id": current_user["email"],
                "status": "Purchased",
                "order_date": datetime.now()
            })

        return jsonify({"message": "The purchase was succesfully completed"}),200
    except Exception as e:
        return jsonify({"message":"Something went wrong"}),404

@app.route("/products", methods=["POST"])
def add_product():
    try:
        request_data = request.json["product"]
        cached_products = get_cached_products()
        product = find_product_from_cache("name", request_data["name"])

        if product is not None:
            return jsonify({"message": "The resource already exists"}), 409
        
        result = products_collection.insert_one(request_data)
        request_data["id"] = str(result.inserted_id)
        del request_data["_id"]
        if cached_products is None:
            cached_products = [request_data]
        else:
            cached_products.append(request_data)
        redis_client.set('products', json.dumps(cached_products))
        return jsonify({"message": "Succesfully added"}), 200

    except Exception as e:
        print("the exception", e)
        return jsonify({"message" : "Something went wrong"}), 404

@app.route("/product/<id>", methods=["DELETE"])
def delete_product(id):
    try:
        product = find_product_from_cache("id", id)
        if product is None:
            return jsonify({"message": "The item was not found"}), 404
        
        filtered_products = delete_product_from_cache(id)
        products_collection.delete_many({"_id": ObjectId(id)})
        redis_client.set("products", json.dumps(filtered_products))
        return jsonify({"message": "Succesfully removed"}), 200
    
    except Exception as e:
        print(e)
        return jsonify({"message" : "Something went wrong"}), 404
    
@app.route("/product/<id>", methods=["PUT"])
def update_product(id):
    try:
        update_data = request.json["product"]
        product = find_product_from_cache("id", id)
        if product is None:
            return jsonify({"message": "The item was not found"}), 404
        
        products_collection.update_many({'_id': ObjectId(id)}, {'$set': update_data})
        update_cached_products(id, update_data)
        return jsonify({"message": "Succesfully updated"}), 200
        
    except Exception as e:
        print("the exception", e)
        return jsonify({"message": "Something went wrong"}), 404
    
