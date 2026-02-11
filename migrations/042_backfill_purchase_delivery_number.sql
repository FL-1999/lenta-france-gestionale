UPDATE purchase_deliveries
SET delivery_number = (
    SELECT purchase_orders.order_number || '-' || purchase_deliveries.id
    FROM purchase_orders
    WHERE purchase_orders.id = purchase_deliveries.order_id
)
WHERE delivery_number IS NULL OR TRIM(delivery_number) = '';
