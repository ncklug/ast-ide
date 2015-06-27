document.addEventListener("keypress", function(e) {
    var xhr = new XMLHttpRequest();
    xhr.onreadystatechange = function() {
        if (xhr.readyState == 4 && xhr.status == 200 && !xhr.already_done) {
            xhr.already_done = true;
            as_json = JSON.parse(xhr.responseText);
            var i;
            for (i = 0; i < as_json.length; i++) {
                // TODO: Pass in args
                // TODO: implement context-based namespacing
                window[as_json[i].action].apply(this, as_json[i].args);
            }
        }
    }
    xhr.open('POST', '/key_event', true);
    xhr.send(String.fromCharCode(e.which));
})


