import java.io.File;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import javax.xml.XMLConstants;
import javax.xml.transform.stream.StreamSource;
import javax.xml.validation.Schema;
import javax.xml.validation.SchemaFactory;
import javax.xml.validation.Validator;
import org.xml.sax.ErrorHandler;
import org.xml.sax.SAXParseException;

final class XsdValidator {
    private static String clean(String value) {
        return value == null ? "" : value.replace('\t', ' ').replace('\n', ' ').replace('\r', ' ');
    }

    private static void diagnostic(String document, String severity, SAXParseException error) {
        byte[] message = clean(error.getMessage()).getBytes(StandardCharsets.UTF_8);
        String encoded = Base64.getEncoder().encodeToString(message);
        System.out.println(
            clean(document) + "\t" + severity + "\t" + error.getLineNumber()
            + "\t" + error.getColumnNumber() + "\t" + encoded
        );
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            throw new IllegalArgumentException("usage: XsdValidator SCHEMA XML...");
        }
        SchemaFactory factory = SchemaFactory.newInstance(XMLConstants.W3C_XML_SCHEMA_NS_URI);
        factory.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
        factory.setProperty(XMLConstants.ACCESS_EXTERNAL_DTD, "");
        factory.setProperty(XMLConstants.ACCESS_EXTERNAL_SCHEMA, "file");
        Schema schema = factory.newSchema(new File(args[0]));
        for (int index = 1; index < args.length; index++) {
            String document = args[index];
            Validator validator = schema.newValidator();
            validator.setProperty(XMLConstants.ACCESS_EXTERNAL_DTD, "");
            validator.setProperty(XMLConstants.ACCESS_EXTERNAL_SCHEMA, "file");
            validator.setErrorHandler(new ErrorHandler() {
                public void warning(SAXParseException error) {
                    diagnostic(document, "warning", error);
                }
                public void error(SAXParseException error) { diagnostic(document, "error", error); }
                public void fatalError(SAXParseException error) {
                    diagnostic(document, "error", error);
                }
            });
            try {
                validator.validate(new StreamSource(new File(document)));
            } catch (SAXParseException error) {
                // Fatal diagnostics may be delivered both to the handler and as
                // an exception. The handler owns the emitted record.
            }
        }
    }
}
