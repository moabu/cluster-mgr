import React, {Component} from "react";
import ReactDOM from "react-dom";
import axios from 'axios';


const LogItem = ({id, action, state, output, server}) => {
    const getState = () => {
        if (state === 'running'){
            return <i className="glyphicon glyphicon-flash text-warning"></i>;
        }
        else if (state === 'fail'){
            return <i className="glyphicon glyphicon-remove-circle text-danger"></i>;
        }
        else if (state === 'success'){
            return <i className="glyphicon glyphicon-ok-circle text-success"></i>;
        }
        else if (state === 'complete'){
            return <i className="glyphicon glyphicon-ok text-info"></i>;
        }
        return state;
    };
    return (
        <div id={"logItem_"+id} className="log-item">
            <p className={"command command-"+state}>{getState()} <span className="host">root@{server}:~# </span>{action}</p>
            <pre>{output}</pre>
        </div>
    );
};

const LogContainer = (props) => {
    const {items, server} = props;
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
        <div className="log-body">
            {logItems}
        </div>
    );
};

class Logger extends Component {
    constructor (props) {
        super(props);
        this.state = {
            logData: {
                messages: []
            }
        };
    }

    componentDidMount() {
        this.timerID = setInterval(
            () => this.fetchData(),
            1000
        );
    }

    fetchData() {
        console.log(this);
        const self = this;
        const id = document.clustermgr.task_id;
        axios.get("/log/"+id).then(
            (response) => {
                self.setState({logData: response.data})
            }
        );
    }

    componentWillUnmount() {
        clearInterval(this.timerID);
    }

    render() {
        const server = "example.com";
        console.log(this.state.logData);
        return (
            <div className="logger">
                <div className="row log-header">
                    <div className="col-md-8">
                        <h5>{"Setting up server : " + server}</h5>
                    </div>
                    <div className="col-md-4">
                    </div>
                </div>
                <LogContainer items={this.state.logData.messages} server={server}/>;
            </div>
        )

    }
}

ReactDOM.render(
    <Logger/>,
    document.getElementById('log_root')
);
