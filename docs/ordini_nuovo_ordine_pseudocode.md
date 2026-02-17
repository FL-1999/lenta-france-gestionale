# Pseudocodice dettagliato

## API supplier by id
```pseudo
GET /api/suppliers/{id}
  require manager
  supplier = query Supplier by id and is_active
  if not found -> 404
  return {name, email, phone, contact_name, contact_email}
```

## API create ordine
```pseudo
POST /api/ordini
  require manager
  validate payload.supplier_id, payload.lines
  supplier = load supplier
  parse lines -> (description, qty, optional item_id)
  order = create_order_with_lines(...)
  order.contact_name = payload.contact_name OR supplier.contact_name
  order.recipient_email = payload.recipient_email OR supplier.contact_email OR supplier.email
  commit
  return {ok, order_id, order_number}
```

## API preview email
```pseudo
POST /api/ordini/email-preview
  require manager
  validate supplier_id
  supplier = load supplier
  build fake PurchaseOrder in memory using payload
  destination = resolve destination label
  (subject, body) = build_order_email(fake_order, lang, destination, recipient_name)
  mailto = encode(recipient + subject + body)
  return preview object
```

## Frontend nuovo ordine
```pseudo
on supplier change:
  if none -> show empty-state
  if new supplier -> show new supplier fields
  else:
    show loading
    fetch /api/suppliers/{id}
    fill read-only card (name/email/phone)
    prefill contact_name and recipient_email if empty
```

## Frontend wizard
```pseudo
on load:
  hydrate supplier defaults
on click 'Genera anteprima':
  gather language, destination, recipient
  POST /api/ordini/email-preview
  fill subject + body + mailto href
on click 'Copia testo':
  copy subject+body in clipboard
```
