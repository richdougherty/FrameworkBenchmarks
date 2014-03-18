package controllers;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import play.mvc.Controller;
import play.mvc.Result;

public class Application extends Controller {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    public static Result json() {
        final ObjectNode result = OBJECT_MAPPER.createObjectNode();
        result.put("message", "Hello World!");
        return ok(result);
    }

}
