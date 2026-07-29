/* static/js/order_form.js -- live order summary preview; server revalidates on submit. */

document.addEventListener("DOMContentLoaded", function () {
    var quantityInputs = document.querySelectorAll(".quantity-input");
    var deliveryCharge = window.BREADFLOW_DELIVERY_CHARGE || 0;

    var subtotalEl = document.getElementById("summary-subtotal");
    var gstEl = document.getElementById("summary-gst");
    var totalEl = document.getElementById("summary-total");

    function formatMoney(value) {
        return "$" + value.toFixed(2);
    }

    function recalculate() {
        var subtotal = 0;
        quantityInputs.forEach(function (input) {
            var quantity = parseInt(input.value, 10);
            var price = parseFloat(input.dataset.price);
            if (quantity > 0 && !isNaN(price)) {
                subtotal += quantity * price;
            }
        });

        var gst = deliveryCharge * 0.10;
        var total = subtotal + deliveryCharge + gst;

        subtotalEl.textContent = formatMoney(subtotal);
        gstEl.textContent = formatMoney(gst);
        totalEl.textContent = formatMoney(total);
    }

    quantityInputs.forEach(function (input) {
        input.addEventListener("input", recalculate);
    });

    recalculate();
});
