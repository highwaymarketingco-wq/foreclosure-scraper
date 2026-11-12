// Run this in browser DevTools console on the Tyler page that worked
// Copy the entire output and save it

console.log("=== TYLER SESSION CAPTURE ===");
console.log("\n--- COOKIES ---");
console.log(document.cookie);

console.log("\n--- LOCAL STORAGE ---");
console.log(JSON.stringify(localStorage));

console.log("\n--- SESSION STORAGE ---");
console.log(JSON.stringify(sessionStorage));

console.log("\n--- CURRENT URL ---");
console.log(window.location.href);

console.log("\n--- USER AGENT ---");
console.log(navigator.userAgent);

console.log("\n=== END CAPTURE ===");
