/*
static/js/login.js -- login page interactivity only.

Two small, self-contained behaviours, deliberately kept out of a
framework (CLAUDE.md: vanilla JS only if needed):
  1. Role tab switching -- purely visual + updates the hidden `role`
     field; the server independently validates this value on submit.
  2. Password show/hide toggle.
Neither behaviour touches the network or does any validation itself --
all real validation happens server-side in User.authenticate().
*/

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
