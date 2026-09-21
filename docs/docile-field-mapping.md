# DocILE to InvoiceOps field mapping

This mapping is deliberately narrower than the DocILE label inventory. DocILE defines a field by
its business meaning, not merely by nearby label text. InvoiceOps exports only fields whose
semantics its current `0.2.0` schema can represent.

## Supported KILE fields

| DocILE field | InvoiceOps field | Rationale |
|---|---|---|
| `document_id` | `invoice_number` | The main document number is the invoice number inside the invoice-only InvoiceOps workflow. Results on non-invoice DocILE documents must be interpreted separately. |
| `date_issue` | `invoice_date` | Both are the document issue date. |
| `amount_total_net` | `subtotal` | Both are the document total before tax. |
| `amount_total_tax` | `tax` | Both are the aggregate document tax amount. |
| `amount_total_gross` | `total` | Both are the document total including tax. |

## Supported LIR fields

| DocILE field | InvoiceOps field | Rationale |
|---|---|---|
| `line_item_description` | `description` | Goods or services description for one line item. |
| `line_item_quantity` | `quantity` | Quantity for one line item. |

## Ambiguous fields intentionally excluded

| DocILE field | Reason for exclusion |
|---|---|
| `amount_due` | A payable balance can differ from gross invoice total because of prior payments, credits or adjustments. |
| `currency_code_amount_due` | A currency adjacent to amount due is not guaranteed to be the global invoice currency. |
| `line_item_amount_gross`, `line_item_amount_net` | InvoiceOps `line_total` does not encode a gross-versus-net tax basis. |
| `line_item_unit_price_gross`, `line_item_unit_price_net` | InvoiceOps `unit_price` does not encode a gross-versus-net tax basis. |
| `order_id`, `customer_order_id`, `vendor_order_id` | Order references are not invoice numbers. |
| tax-detail fields | Tax-breakdown rows are not equivalent to the single aggregate InvoiceOps tax field. |
| discount fields | InvoiceOps currently has no discount field. |

## Unsupported schema areas

Bank identifiers, payment references and terms, due dates, customer/vendor names and addresses,
registration identifiers, tax identifiers, item codes, positions, dates, currencies, discounts,
taxes, units of measure, weights, people and HTS numbers are omitted because InvoiceOps `0.2.0`
does not model them. No semantically adjacent substitute is used.

The official DocILE label inventory must be profiled from the downloaded validation split before
publishing a real-data report. Unknown future labels remain unsupported until explicitly reviewed.

## References

- [DocILE repository and evaluator documentation](https://github.com/rossumai/docile)
- [DocILE benchmark paper and field definitions](https://arxiv.org/abs/2302.05658)
