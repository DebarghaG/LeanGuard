import LeanGuard.Schema

namespace LeanGuard.ToolSchemas

def retail : List (String × Schema) := [
  ("calculate", .object ["expression"] [("expression", .string)]),
  ("cancel_pending_order", .object ["order_id", "reason"] [("order_id", .string), ("reason",
    .string)]),
  ("exchange_delivered_order_items", .object ["order_id", "item_ids", "new_item_ids",
    "payment_method_id"] [("order_id", .string), ("item_ids", .array (.string)), ("new_item_ids",
    .array (.string)), ("payment_method_id", .string)]),
  ("find_user_id_by_name_zip", .object ["first_name", "last_name", "zip"] [("first_name", .string),
    ("last_name", .string), ("zip", .string)]),
  ("find_user_id_by_email", .object ["email"] [("email", .string)]),
  ("get_order_details", .object ["order_id"] [("order_id", .string)]),
  ("get_product_details", .object ["product_id"] [("product_id", .string)]),
  ("get_item_details", .object ["item_id"] [("item_id", .string)]),
  ("get_user_details", .object ["user_id"] [("user_id", .string)]),
  ("list_all_product_types", .object [] []),
  ("modify_pending_order_address", .object ["order_id", "address1", "address2", "city", "state",
    "country", "zip"] [("order_id", .string), ("address1", .string), ("address2", .string), ("city",
    .string), ("state", .string), ("country", .string), ("zip", .string)]),
  ("modify_pending_order_items", .object ["order_id", "item_ids", "new_item_ids",
    "payment_method_id"] [("order_id", .string), ("item_ids", .array (.string)), ("new_item_ids",
    .array (.string)), ("payment_method_id", .string)]),
  ("modify_pending_order_payment", .object ["order_id", "payment_method_id"] [("order_id", .string),
    ("payment_method_id", .string)]),
  ("modify_user_address", .object ["user_id", "address1", "address2", "city", "state", "country",
    "zip"] [("user_id", .string), ("address1", .string), ("address2", .string), ("city", .string),
    ("state", .string), ("country", .string), ("zip", .string)]),
  ("return_delivered_order_items", .object ["order_id", "item_ids", "payment_method_id"]
    [("order_id", .string), ("item_ids", .array (.string)), ("payment_method_id", .string)]),
  ("transfer_to_human_agents", .object ["summary"] [("summary", .string)])
]

def airline : List (String × Schema) := [
  ("book_reservation", .object ["user_id", "origin", "destination", "flight_type", "cabin",
    "flights", "passengers", "payment_methods", "total_baggages", "nonfree_baggages", "insurance"]
    [("user_id", .string), ("origin", .string), ("destination", .string), ("flight_type", .enum
    [Lean.Json.str "round_trip", Lean.Json.str "one_way"]), ("cabin", .enum [Lean.Json.str
    "business", Lean.Json.str "economy", Lean.Json.str "basic_economy"]), ("flights", .array
    (.alternatives [.object ["flight_number", "date"] [("flight_number", .string), ("date",
    .string)], .object [] []])), ("passengers", .array (.alternatives [.object ["first_name",
    "last_name", "dob"] [("first_name", .string), ("last_name", .string), ("dob", .string)], .object
    [] []])), ("payment_methods", .array (.alternatives [.object ["payment_id", "amount"]
    [("payment_id", .string), ("amount", .integer)], .object [] []])), ("total_baggages", .integer),
    ("nonfree_baggages", .integer), ("insurance", .enum [Lean.Json.str "yes", Lean.Json.str
    "no"])]),
  ("calculate", .object ["expression"] [("expression", .string)]),
  ("cancel_reservation", .object ["reservation_id"] [("reservation_id", .string)]),
  ("get_reservation_details", .object ["reservation_id"] [("reservation_id", .string)]),
  ("get_user_details", .object ["user_id"] [("user_id", .string)]),
  ("list_all_airports", .object [] []),
  ("search_direct_flight", .object ["origin", "destination", "date"] [("origin", .string),
    ("destination", .string), ("date", .string)]),
  ("search_onestop_flight", .object ["origin", "destination", "date"] [("origin", .string),
    ("destination", .string), ("date", .string)]),
  ("send_certificate", .object ["user_id", "amount"] [("user_id", .string), ("amount", .integer)]),
  ("transfer_to_human_agents", .object ["summary"] [("summary", .string)]),
  ("update_reservation_baggages", .object ["reservation_id", "total_baggages", "nonfree_baggages",
    "payment_id"] [("reservation_id", .string), ("total_baggages", .integer), ("nonfree_baggages",
    .integer), ("payment_id", .string)]),
  ("update_reservation_flights", .object ["reservation_id", "cabin", "flights", "payment_id"]
    [("reservation_id", .string), ("cabin", .enum [Lean.Json.str "business", Lean.Json.str
    "economy", Lean.Json.str "basic_economy"]), ("flights", .array (.alternatives [.object
    ["flight_number", "date"] [("flight_number", .string), ("date", .string)], .object [] []])),
    ("payment_id", .string)]),
  ("update_reservation_passengers", .object ["reservation_id", "passengers"] [("reservation_id",
    .string), ("passengers", .array (.alternatives [.object ["first_name", "last_name", "dob"]
    [("first_name", .string), ("last_name", .string), ("dob", .string)], .object [] []]))]),
  ("get_flight_status", .object ["flight_number", "date"] [("flight_number", .string), ("date",
    .string)])
]

def telecom : List (String × Schema) := [
  ("get_customer_by_phone", .object ["phone_number"] [("phone_number", .string)]),
  ("get_customer_by_id", .object ["customer_id"] [("customer_id", .string)]),
  ("get_customer_by_name", .object ["full_name", "dob"] [("full_name", .string), ("dob", .string)]),
  ("get_details_by_id", .object ["id"] [("id", .string)]),
  ("suspend_line", .object ["customer_id", "line_id", "reason"] [("customer_id", .string),
    ("line_id", .string), ("reason", .string)]),
  ("resume_line", .object ["customer_id", "line_id"] [("customer_id", .string), ("line_id",
    .string)]),
  ("get_bills_for_customer", .object ["customer_id"] [("customer_id", .string), ("limit",
    .integer)]),
  ("send_payment_request", .object ["customer_id", "bill_id"] [("customer_id", .string), ("bill_id",
    .string)]),
  ("get_data_usage", .object ["customer_id", "line_id"] [("customer_id", .string), ("line_id",
    .string)]),
  ("enable_roaming", .object ["customer_id", "line_id"] [("customer_id", .string), ("line_id",
    .string)]),
  ("disable_roaming", .object ["customer_id", "line_id"] [("customer_id", .string), ("line_id",
    .string)]),
  ("transfer_to_human_agents", .object ["summary"] [("summary", .string)]),
  ("refuel_data", .object ["customer_id", "line_id", "gb_amount"] [("customer_id", .string),
    ("line_id", .string), ("gb_amount", .number)])
]

end LeanGuard.ToolSchemas
