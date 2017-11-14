import ReactDOM from "react-dom";
import Logger from "./logger/Logger";

for (let i=0; i < document.servers.length(); i++) {
    ReactDOM.render(
        <Logger server={document.servers.hostname} />,
        document.getElementById('logger_'+i)
    );
}

