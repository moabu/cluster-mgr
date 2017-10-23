import React, {Component} from "react";
import ReachDOM from "react-dom";
import styles from './Logger.css';


/**
 *
 *  log_item {
 *      id: unique_id,
 *      action: command being run or any action,
 *      state: pending, success, fail,
 *      output: any value returned by the action
 *  }
 *
 *  log_container {
 *      // container that hold a number of log_items
 *  }
 *
 *  app{
 *     // holds the the conatiner or multiple containers if necessary
 *  }
 *
 *
 */
const LogItem = ({id, action, state, output, server}) => {
    const getState = () => {
        if (state === 'running'){
            return <i className="glyphicon glyphicon-flash"></i>;
        }
        else if (state === 'fail'){
            return <i className="glyphicon glyphicon-remove-circle"></i>;
        }
        else if (state === 'success'){
            return <i className="glyphicon glyphicon-ok-circle"></i>;
        }
        return state;
    };
    return (
        <div id={"logItem_"+id} className="logItem">
            <p className={"command command-"+state}>{getState()} <span className="host">root@{server}:~# </span>{action}</p>
            <pre>{output}</pre>
        </div>
    );
};

const LogContainer = (props) => {
    const {items, title, server} = props;
    const logItems = items.map(itemInfo => {
        const {id, action, state, output} = itemInfo;

        return (
            <LogItem
                key={id}
                id={id}
                action={action}
                state={state}
                output={output}
                server={server}
            />
        );

    });

    return (
        <div className="logContainer">
            <p className="containerTitle">{title + " : " + server}</p>
            {logItems}
        </div>
    );
}

class Logger extends Component {
    constructor (props) {
        super(props);

    }

    render() {
        const logData = [
            {id:1, action: 'apt-get update -y', state: "success", output: "update succeded"},
            {id:2, action: 'service solserver restart', state: "fail", output: "Service restarted"},
            {id:3, action: 'apt-get install redis-server', state: "running", output: "some output being streamed"},
        ];
        return <LogContainer items={logData} title="Setting up server" server="example.com"/>;
    }
}

ReachDOM.render(
    <Logger/>,
    document.getElementById('log_root')
);
