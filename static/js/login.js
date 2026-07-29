/* static/js/login.js -- role tab switching + password show/hide. Server re-validates everything. */

document.addEventListener("DOMContentLoaded", function () {
    var roleInput = document.getElementById("role-input");
    var tabs = document.querySelectorAll(".role-tab");

    tabs.forEach(function (tab) {
        tab.addEventListener("click", function () {
            tabs.forEach(function (t) {
                t.classList.remove("active");
                t.setAttribute("aria-selected", "false");
            });
            tab.classList.add("active");
            tab.setAttribute("aria-selected", "true");
            roleInput.value = tab.dataset.role;
        });
    });

    var passwordField = document.getElementById("password");
    var toggleButton = document.getElementById("password-toggle");

    toggleButton.addEventListener("click", function () {
        var isHidden = passwordField.type === "password";
        passwordField.type = isHidden ? "text" : "password";
        toggleButton.classList.toggle("is-visible", isHidden);
        toggleButton.setAttribute("aria-label", isHidden ? "Hide password" : "Show password");
    });
});
